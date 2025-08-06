from dotenv import load_dotenv

from google.genai import types
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import google, noise_cancellation, silero, openai, deepgram,rime
from prompts import AGENT_INSTRUCTION, SESSION_INSTRUCTION
from tools import (
    search_web, 
    get_weather, 
    send_email, 
    camera_on,
    camera_off,
    switch_camera,
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
                # so far this model is fucking good at calling tools, and great for vision
                model="gemini-live-2.5-flash-preview",
                # The best model for now, but very expensive, bad for calling tools
                # model="gemini-2.5-flash-preview-native-audio-dialog",
                # Best for speech and vision, bad for calling tools
                # model="gemini-2.5-flash-exp-native-audio-thinking-dialog",
            ),
            # Fuckk this model is fucking good at calling tools, but nope for vision
            # llm=openai.realtime.RealtimeModel(
            #     model="gpt-4o-realtime-preview",
            #     voice="sage",
            #     modalities=["audio", "text"]
            # ),
            # stt= deepgram.STT(),
            # tts= rime.TTS(),
            vad=silero.VAD.load(),
            tools=[
                search_web, 
                get_weather, 
                send_email, 
                camera_on,
                camera_off,
                switch_camera,
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