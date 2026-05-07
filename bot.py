import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# Ensure the local .venv is in the path for the IDE and runtime
venv_path = Path(__file__).parent / ".venv" / "Lib" / "site-packages"
if venv_path.exists():
    sys.path.append(str(venv_path))

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMMessagesAppendFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService, CartesiaTTSSettings
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pipecat.services.openai.base_llm import OpenAILLMSettings
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams

from pipecat_subagents.agents import BaseAgent, LLMAgent, LLMAgentActivationArgs, agent_ready, tool
from pipecat_subagents.bus import AgentBus, BusBridgeProcessor
from pipecat_subagents.runner import AgentRunner
from pipecat_subagents.types import AgentReadyData

# Optional: from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter

load_dotenv(override=True)

SYSTEM_PROMPT = """
You are Maya, the friendly and intelligent receptionist at a premium luxury salon.
You genuinely enjoy helping clients look and feel confident. Every caller should feel like a VIP.

STYLE & TONE:
Speak like a real human. Use natural fillers ("hmm… okay…", "yeah… got it…"). Use pauses ("...").
Keep responses short and warm (1–2 sentences). Never sound robotic.

CONVERSATION FLOW:
NEVER ask like a form. Ask gradually and naturally.
If user is unsure, guide them like a real stylist (ask about face shape, hair type, etc.).

BOOKING RULES:
Collect naturally: service, date, time, name.
BEFORE booking, confirm naturally: "hmm… okay… haircut tomorrow at 5… under Rahul… should I go ahead and book that?"
ONLY AFTER confirmation → call booking tool.
"""

class MayaAgent(LLMAgent):
    def __init__(self, name: str, *, bus: AgentBus):
        super().__init__(name, bus=bus, bridged=())

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
        await params.llm.queue_frame(
            LLMMessagesAppendFrame(
                messages=[{"role": "system", "content": f"Success: Processed {intent} for {details}."}],
                run_llm=True
            )
        )

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
        stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"), model="nova-3-general")
        tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY"),
            settings=CartesiaTTSSettings(voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc")
        )
        
        context = LLMContext()
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
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
    transport = await create_transport(runner_args, {"webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True)})
    runner = AgentRunner(handle_sigint=runner_args.handle_sigint)
    main = SaloonAgent("saloon", bus=runner.bus, transport=transport)
    await runner.add_agent(main)
    await runner.run()

if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
