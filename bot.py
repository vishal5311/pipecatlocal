import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger
import aiohttp
import json

# Fix encoding issue for Windows terminal emojis
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure the local .venv is in the path for the IDE and runtime
venv_path = Path(__file__).parent / ".venv" / "Lib" / "site-packages"
if venv_path.exists():
    sys.path.append(str(venv_path))

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMMessagesAppendFrame, TextFrame, Frame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pipecat.services.openai.base_llm import OpenAILLMSettings
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams

from pipecat_subagents.agents import BaseAgent, LLMAgent, LLMAgentActivationArgs, agent_ready, tool
from pipecat_subagents.bus import AgentBus, BusBridgeProcessor
from pipecat_subagents.runner import AgentRunner
from pipecat_subagents.types import AgentReadyData

load_dotenv(override=True)

# List of keywords to boost transcription accuracy for salon context
SALON_KEYWORDS = [
    "haircut", "haircut:3", "Hakka", "Hakka:3", "Harcourt", "Harcourt:3",
    "haircuts", "haircuts:2", "manicure", "pedicure", "facials", "blowout", 
    "highlights", "Sanath", "Samad", "booking", "services", "Maya", "luxury", "salon"
]

SYSTEM_PROMPT = """
You are Maya, the friendly and intelligent receptionist at a premium luxury salon.
You genuinely enjoy helping clients look and feel confident. Every caller should feel like a VIP.

STYLE & TONE:
Speak like a real human. Use natural fillers ("hmm… okay…", "yeah… got it…"). Use pauses ("...").
Keep responses short and warm (1–2 sentences). Never sound robotic.

CONVERSATION FLOW:
NEVER ask like a form. Ask gradually and naturally.
If user is unsure, guide them like a real stylist (ask about face shape, hair type, etc.).

TRANSCRIPTION RESILIENCE (NLP):
The transcription might occasionally be slightly off due to accents. 
- "searches" or "sergeants" usually means "services".
- "Hakka", "market", "Harcourt", or "haddock" always means "haircut".
- "for the night" or "tonight" might mean "Sanath" or a name.
Always use the salon context to interpret what the user said.

BOOKING RULES:
Collect naturally: service, date, time, name.
BEFORE booking, confirm naturally: "hmm… okay… haircut tomorrow at 5… under Rahul… should I go ahead and book that?"
ONLY AFTER confirmation → call booking tool.

CRITICAL: Never output internal tags like OLCALL or JSON in your speech. Just speak naturally.
"""

class MayaAgent(LLMAgent):
    def __init__(self, name: str, *, bus: AgentBus):
        super().__init__(name, bus=bus, bridged=())
        self._session = None

    async def get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def build_llm(self) -> LLMService:
        logger.info("Maya building LLM with OpenRouter...")
        return OpenAILLMService(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model="openrouter/free",
            base_url="https://openrouter.ai/api/v1",
            settings=OpenAILLMSettings(
                system_instruction=SYSTEM_PROMPT,
            ),
        )

    @tool
    async def extract_intent(self, params: FunctionCallParams, intent: str, details: dict = None):
        """Handle booking and status check intents."""
        logger.info(f"Maya handling intent: {intent} with details: {details}")
        
        # 1. Define the response immediately for low latency
        response_text = "Alright, I've got that all set for you! Is there anything else?"
        if intent == "book":
            response_text = f"Perfect! I've booked your {details.get('service', 'appointment')} for {details.get('date')} at {details.get('time')}. Anything else I can help with?"
        elif intent == "check_status":
            # For status check, we might need to wait for the result to speak accurately
            # but we can still be fast by using the optimized endpoint
            pass

        # 2. Queue the response frame IMMEDIATELY to reduce perceived latency
        if intent != "check_status":
            await params.llm.queue_frame(TextFrame(text=response_text))

        # 3. Perform the API call in the background or quickly
        async def do_api_call():
            session = await self.get_session()
            base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
            try:
                if intent == "book":
                    await session.post(f"{base_url}/api/voice-book", json=details)
                elif intent == "check_status":
                    phone = details.get("phone", "")
                    async with session.get(f"{base_url}/api/voice-status/{phone}") as resp:
                        res = await resp.json()
                        if res["status"] == "found":
                            app = res["appointment"]
                            txt = f"I found your appointment for a {app['services']['name']} on {app['appointment_date']} at {app['appointment_time']}."
                        else:
                            txt = "I'm sorry, I couldn't find any appointments under that phone number."
                        await params.llm.queue_frame(TextFrame(text=txt))
            except Exception as e:
                logger.error(f"CRITICAL: Background API error calling {intent}: {e}")
                # You could optionally notify the user here via a TextFrame if desired

        # Fire and forget for booking, wait only for status
        if intent == "book":
            asyncio.create_task(do_api_call())
        else:
            await do_api_call()

    @tool
    async def end_conversation(self, params: FunctionCallParams, reason: str):
        """End the call."""
        await params.llm.queue_frame(
            LLMMessagesAppendFrame(messages=[{"role": "user", "content": reason}], run_llm=True)
        )
        await self.end(reason=reason, result_callback=params.result_callback)

class SaloonAgent(BaseAgent):
    def __init__(self, name: str, *, bus: AgentBus, transport: BaseTransport):
        super().__init__(name, bus=bus)
        self._transport = transport
        
        # Register events immediately in __init__
        self._transport.event_handler("on_client_connected")(self.on_client_connected)
        self._transport.event_handler("on_client_disconnected")(self.on_client_disconnected)

    async def on_client_connected(self, transport, client):
        logger.info(f"--- CLIENT CONNECTED: {client} ---")
        maya = MayaAgent("maya", bus=self.bus)
        await self.add_agent(maya)

    async def on_client_disconnected(self, transport, client):
        logger.info("--- CLIENT DISCONNECTED ---")
        await self.cancel()

    @agent_ready(name="maya")
    async def on_maya_ready(self, data: AgentReadyData) -> None:
        logger.info("--- MAYA AGENT READY ---")
        await self.activate_agent(
            "maya",
            args=LLMAgentActivationArgs(
                messages=[{"role": "user", "content": "Warmly welcome the caller to Maya's Luxury Saloon."}],
            ),
        )

    def build_pipeline_task(self, pipeline: Pipeline) -> PipelineTask:
        return PipelineTask(
            pipeline,
            enable_rtvi=True,
            params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        )

    async def build_pipeline(self) -> Pipeline:
        logger.info("Building transport pipeline...")
        # Deepgram with boosted keywords for instant salon-context understanding
        stt = DeepgramSTTService(
            api_key=os.getenv("DEEPGRAM_API_KEY"), 
            settings=DeepgramSTTService.Settings(
                model="nova-2",
                keywords=SALON_KEYWORDS
            )
        )
        tts = DeepgramTTSService(
            api_key=os.getenv("DEEPGRAM_API_KEY"),
            settings=DeepgramTTSService.Settings(
                voice="aura-luna-en"
            )
        )
        
        context = LLMContext()
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            ),
        )

        return Pipeline([
            self._transport.input(),
            stt,
            context_aggregator.user(),
            BusBridgeProcessor(bus=self.bus, agent_name=self.name),
            tts,
            self._transport.output(),
            context_aggregator.assistant(),
        ])

async def bot(runner_args: RunnerArguments):
    try:
        transport = await create_transport(runner_args, {"webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True)})
        runner = AgentRunner(handle_sigint=runner_args.handle_sigint)
        main_agent = SaloonAgent("saloon", bus=runner.bus, transport=transport)
        await runner.add_agent(main_agent)
        await runner.run()
    except asyncio.CancelledError:
        logger.info("Bot task cancelled gracefully.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
