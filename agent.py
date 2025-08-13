from dotenv import load_dotenv

from google.genai import types
from PIL import Image
from livekit.agents.llm import ImageContent
import numpy as np

from livekit import agents
from livekit.agents import AgentSession, Agent, ChatContext, ChatMessage, RoomInputOptions
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
                voice="Leda",
                # so far this model is fucking good at calling tools, and great for vision
                model="gemini-live-2.5-flash-preview",
                # The best model for now, but very expensive, bad for calling tools
                # model="gemini-2.5-flash-preview-native-audio-dialog",
                # Best for speech and vision, bad for calling tools
                # model="gemini-2.5-flash-exp-native-audio-thinking-dialog",
            ),
            # Fuckk this model is fucking good at calling tools, but nope for vision
            # llm=openai.realtime.RealtimeModel(
            #     model="gpt-4o-realtime-preview-2025-06-03",
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
        self._latest_frame = None
        self._video_stream = None
        self._tasks = []
        
    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        if self._latest_frame:
            # Tambahkan ke konten pesan (sesuai implementasi aslinya)
            new_message.content.append(ImageContent(image=self._latest_frame))

            # Convert VideoFrame ke NumPy array (asumsi frame RGB)
            frame_array = self._latest_frame.to_ndarray(format="rgb24")  # bisa juga 'bgr24'

            # Konversi ke Image dan simpan
            image = Image.fromarray(frame_array)
            image.save("latest_frame.png")  # Simpan ke file


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