-- Create services table
CREATE TABLE services (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    duration_minutes INTEGER NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create appointments table
CREATE TABLE appointments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_name TEXT NOT NULL,
    client_phone TEXT NOT NULL,
    service_id UUID REFERENCES services(id),
    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,
    status TEXT DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled', 'completed')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert some default services for a luxury salon
INSERT INTO services (name, description, duration_minutes, price) VALUES
('Luxury Haircut', 'Precision cut including wash and styling.', 60, 150.00),
('Manicure & Pedicure', 'Full nail care with premium polish.', 90, 120.00),
('Rejuvenating Facial', 'Deep cleansing and hydration treatment.', 75, 200.00),
('Blowout', 'Professional wash and blow dry.', 45, 80.00),
('Hair Highlights', 'Full head highlights with premium color.', 180, 350.00);

-- Disable RLS for testing/demo purposes
ALTER TABLE services DISABLE ROW LEVEL SECURITY;
ALTER TABLE appointments DISABLE ROW LEVEL SECURITY;
