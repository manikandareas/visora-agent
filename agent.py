from dotenv import load_dotenv

from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import google, noise_cancellation, silero
from prompts import AGENT_INSTRUCTION, SESSION_INSTRUCTION
from tools import (
    search_web, 
    get_weather, 
    send_email, 
    control_camera, 
)
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

def prewarm(proc: agents.JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

class AssistiveAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=AGENT_INSTRUCTION,
            llm=google.beta.realtime.RealtimeModel(
                voice="Fenrir",
                model="gemini-2.0-flash-live-001",
                # The best model for now, but very expensive
                # model="gemini-2.5-flash-preview-native-audio-dialog",
            ),
            tools=[
                search_web, 
                get_weather, 
                send_email, 
                control_camera, 
            ]
        )
        self.session_id = None
        self.last_frame_analysis = None

async def entrypoint(ctx: agents.JobContext):
    """Main entry point for the agent"""
    try:
        # Initialize session
        session = AgentSession(
                vad=ctx.proc.userdata["vad"],
                turn_detection=MultilingualModel(),
        )
        agent = AssistiveAgent()
        
        # Create user session in database
        # user_id = f"user_{ctx.room.name}"  # Simple user ID based on room name

        await session.start(
            room=ctx.room,
            agent=agent,
            room_input_options=RoomInputOptions(
                video_enabled=True,
                noise_cancellation=noise_cancellation.BVC(),
            ),
        )

        await ctx.connect()

        # Start the conversation
        await session.generate_reply(
            instructions=SESSION_INSTRUCTION,
            allow_interruptions=True,
        )

        logger.info("Agent session started successfully")
        
    except Exception as e:
        logger.error(f"Error in agent entrypoint: {e}")
        raise


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm)
    )