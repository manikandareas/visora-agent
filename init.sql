-- Sessions table for tracking user sessions
CREATE TABLE sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true
);

-- Camera states table for real-time camera control
CREATE TABLE camera_states (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    is_enabled BOOLEAN DEFAULT false,
    camera_type TEXT DEFAULT 'user', -- 'user' for front camera, 'environment' for back camera
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Conversation history for RAG implementation (optional for Phase 2)
CREATE TABLE conversation_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    message_type TEXT NOT NULL, -- 'user' or 'assistant'
    content TEXT NOT NULL,
    metadata JSONB, -- for storing additional context like vision analysis results
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User preferences (optional for Phase 2)
CREATE TABLE user_preferences (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    preference_key TEXT NOT NULL,
    preference_value TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(session_id, preference_key)
);

-- Enable Row Level Security
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE camera_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;

-- Create policies for sessions table
CREATE POLICY "Users can manage their own sessions" ON sessions
    FOR ALL USING (auth.uid()::text = user_id);

-- Create policies for camera_states table
CREATE POLICY "Users can manage camera states for their sessions" ON camera_states
    FOR ALL USING (
        session_id IN (
            SELECT id FROM sessions WHERE user_id = auth.uid()::text
        )
    );

-- Create policies for conversation_history table
CREATE POLICY "Users can access their conversation history" ON conversation_history
    FOR ALL USING (
        session_id IN (
            SELECT id FROM sessions WHERE user_id = auth.uid()::text
        )
    );

-- Create policies for user_preferences table
CREATE POLICY "Users can manage their preferences" ON user_preferences
    FOR ALL USING (
        session_id IN (
            SELECT id FROM sessions WHERE user_id = auth.uid()::text
        )
    );

-- Create indexes for better performance
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_token ON sessions(session_token);
CREATE INDEX idx_camera_states_session_id ON camera_states(session_id);
CREATE INDEX idx_conversation_history_session_id ON conversation_history(session_id);
CREATE INDEX idx_user_preferences_session_id ON user_preferences(session_id);

-- Enable real-time for camera_states table
ALTER PUBLICATION supabase_realtime ADD TABLE camera_states;