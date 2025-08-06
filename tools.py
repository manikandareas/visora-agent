from dotenv import load_dotenv
import logging
from livekit.agents import function_tool, RunContext
import requests
from langchain_community.tools import DuckDuckGoSearchRun
import os
import smtplib
from email.mime.multipart import MIMEMultipart  
from email.mime.text import MIMEText
from typing import Optional
from supabase import Client, acreate_client, create_client
import cv2
import numpy as np
from datetime import datetime
import uuid
import json
import asyncio

load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

async def create_async_supabase():
  supabase = await acreate_client(supabase_url, supabase_key)
  return supabase

import os
import uuid
import logging
from datetime import datetime
import asyncio
from supabase import create_client, Client
from livekit.agents import function_tool

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

async def create_async_supabase():
    supabase = await acreate_client(supabase_url, supabase_key)
    return supabase

@function_tool
async def camera_on(context: RunContext, camera_type: str = "user") -> str:
    """
    Turn on the camera for visual assistance. Use this tool when users need to activate their camera for visual help.
    Args:
        camera_type: Which camera to use - "user" for front-facing camera or "environment" for back camera
    Returns:
        Confirmation message about the camera activation
    """
    try:
        event_payload = {
            "action": "on",
            "camera_type": camera_type,
            "timestamp": datetime.now().isoformat(),
            "event_id": str(uuid.uuid4())[:8],
            "message": "Camera activation requested",
            "is_enabled": True
        }

        async_supabase = await create_async_supabase()
        camera_channel = async_supabase.channel("visora_agent")
        await camera_channel.subscribe()

        asyncio.create_task(camera_channel.send_broadcast(
            "camera_states",
            event_payload
        ))

        logging.info(f"Broadcast camera ON event: {event_payload}")
        camera_name = "back camera" if camera_type == "environment" else "front camera"
        return f"The {camera_name} is now on and ready to help you see your surroundings."

    except Exception as e:
        logging.error(f"Error turning on camera: {e}")
        return "I'm having trouble turning on the camera right now. Please try again."

@function_tool
async def camera_off(context: RunContext) -> str:
    """
    Turn off the camera. Use this tool when users want to deactivate their camera.
    Returns:
        Confirmation message about the camera deactivation
    """
    try:
        event_payload = {
            "action": "off",
            "timestamp": datetime.now().isoformat(),
            "event_id": str(uuid.uuid4())[:8],
            "message": "Camera deactivation requested",
            "is_enabled": False
        }

        async_supabase = await create_async_supabase()
        camera_channel = async_supabase.channel("visora_agent")
        await camera_channel.subscribe()

        asyncio.create_task(camera_channel.send_broadcast(
            "camera_states",
            event_payload
        ))

        logging.info(f"Broadcast camera OFF event: {event_payload}")
        return "The camera has been turned off."

    except Exception as e:
        logging.error(f"Error turning off camera: {e}")
        return "I'm having trouble turning off the camera right now. Please try again."

@function_tool
async def switch_camera(context: RunContext, current_camera_type: str = "user") -> str:
    """
    Switch between front and back cameras. Use this tool when users want to change the active camera.
    Args:
        current_camera_type: The current camera - "user" for front-facing or "environment" for back camera
    Returns:
        Confirmation message about the camera switch
    """
    try:
        new_camera_type = "environment" if current_camera_type == "user" else "user"
        event_payload = {
            "action": "switch",
            "camera_type": current_camera_type,
            "new_camera_type": new_camera_type,
            "timestamp": datetime.now().isoformat(),
            "event_id": str(uuid.uuid4())[:8],
            "message": f"Camera switch requested: {current_camera_type} -> {new_camera_type}",
            "is_enabled": True
        }

        async_supabase = await create_async_supabase()
        camera_channel = async_supabase.channel("visora_agent")
        await camera_channel.subscribe()

        asyncio.create_task(camera_channel.send_broadcast(
            "camera_states",
            event_payload
        ))

        camera_name = "back camera" if new_camera_type == "environment" else "front camera"
        logging.info(f"Camera switched to {new_camera_type}")
        return f"Switched to the {camera_name}."

    except Exception as e:
        logging.error(f"Error switching camera: {e}")
        return "I'm having trouble switching the camera right now. Please try again."

@function_tool
async def get_weather(
    context: RunContext,
    city: str = "Jakarta"
) -> str:
    """
    Get current weather information for any location. Use this tool when users ask about weather conditions, 
    temperature, if it's raining, if they should bring an umbrella, or anything related to outdoor conditions 
    and weather planning.
    
    Args:
        city: The city or location to get weather information for
    
    Returns:
        Current weather conditions and helpful details for planning activities
    """
    try:
        response = requests.get(f"https://wttr.in/{city}?format=j1", timeout=10)
        if response.status_code == 200:
            data = response.json()
            current = data['current_condition'][0]
            
            # Create natural weather description
            temp_c = current['temp_C']
            feels_like = current['FeelsLikeC']
            humidity = current['humidity']
            wind_speed = current['windspeedKmph']
            weather_desc = current['weatherDesc'][0]['value']
            
            # Build conversational weather report
            description = f"The weather in {city} right now is {weather_desc.lower()}. "
            description += f"It's {temp_c} degrees Celsius, but feels like {feels_like} degrees. "
            description += f"Humidity is at {humidity} percent with winds at {wind_speed} kilometers per hour. "
            
            # Add helpful suggestions
            if int(temp_c) >= 30:
                description += "It's quite warm today, so staying hydrated is important."
            elif int(temp_c) <= 15:
                description += "It's cool today, so you might want to bring a jacket."
            
            if "rain" in weather_desc.lower():
                description += " You'll want to bring an umbrella."
            
            logging.info(f"Weather data retrieved successfully for {city}")
            return description.strip()
        else:
            logging.warning(f"Weather API returned status {response.status_code} for {city}")
            return f"I couldn't get weather information for {city} right now. Please try again later."
    except requests.RequestException as e:
        logging.error(f"Network error retrieving weather for {city}: {e}")
        return f"I'm having trouble connecting to the weather service for {city}."
    except Exception as e:
        logging.error(f"Unexpected error retrieving weather for {city}: {e}")
        return f"Something went wrong while getting weather information for {city}."

@function_tool
async def search_web(
    context: RunContext,
    query: str
) -> str:
    """
    Search the internet for current information, news, facts, or answers to questions. Use this tool when users 
    ask about current events, want to find information about topics, need facts or explanations, or ask questions 
    that require up-to-date information from the web.
    
    Args:
        query: What the user wants to search for or learn about
    
    Returns:
        Current information and search results from the web
    """
    try:
        search = DuckDuckGoSearchRun()
        raw_results = search.run(tool_input=query)
        
        # Format for natural speech
        formatted_results = f"Here's what I found about {query}: {raw_results}"
        
        # Add helpful follow-up
        formatted_results += " Would you like me to search for anything more specific about this topic?"
        
        logging.info(f"Web search completed successfully for query: '{query}'")
        return formatted_results.strip()
        
    except Exception as e:
        logging.error(f"Error during web search for '{query}': {e}")
        return f"I'm having trouble searching for information about {query} right now. The internet connection might be having issues."

@function_tool
async def send_email(
    context: RunContext,
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    """
    Send emails to people. Use this tool when users want to send messages, share information via email, 
    communicate with someone through email, or compose and send any kind of email message.
    
    Args:
        to_email: The email address to send the message to
        subject: The subject line for the email
        message: The content of the email message
        cc_email: Optional additional email address to copy on the message
    
    Returns:
        Confirmation that the email was sent successfully or information about any problems
    """
    try:
        # Gmail SMTP configuration
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        
        # Get credentials from environment variables
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        
        if not gmail_user or not gmail_password:
            logging.error("Gmail credentials missing in environment")
            return "I can't send emails right now because the email credentials aren't set up properly."
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add CC if provided
        recipients = [to_email]
        if cc_email:
            msg['Cc'] = cc_email
            recipients.append(cc_email)
        
        # Attach message body
        msg.attach(MIMEText(message, 'plain'))
        
        # Connect to Gmail SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()  # Enable TLS encryption
        server.login(gmail_user, gmail_password)
        
        # Send email
        text = msg.as_string()
        server.sendmail(gmail_user, recipients, text)
        server.quit()
        
        logging.info(f"Email sent successfully to {to_email}" + (f" and CC to {cc_email}" if cc_email else ""))
        
        confirmation = f"Your email has been sent successfully to {to_email}"
        if cc_email:
            confirmation += f" with a copy to {cc_email}"
        confirmation += f" at {datetime.now().strftime('%I:%M %p')}"
        
        return confirmation
        
    except smtplib.SMTPAuthenticationError:
        logging.error("Gmail authentication failed")
        return "I couldn't send the email because there's an authentication problem with the email account."
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error occurred: {e}")
        return f"There was a problem sending the email: {str(e)}"
    except Exception as e:
        logging.error(f"Unexpected error sending email: {str(e)}")
        return f"Something went wrong while sending the email: {str(e)}"

def get_session_id(context) -> str:
    """
    Generate consistent session ID based on context for session management.
    Handles both JobContext (from agent.py) and RunContext (from tool calls).
    Ensures the same session ID is used across all functions within a session.
    """
    import uuid

    # Try to get room name - handle different context types
    room_name = "default_room"
    
    # For JobContext (used in agent.py entrypoint)
    if hasattr(context, 'room') and hasattr(context.room, 'name'):
        room_name = context.room.name
    # For RunContext (used in tool calls) - try different attributes
    elif hasattr(context, 'room') and hasattr(context.room, 'name'):
        room_name = context.room.name
    elif hasattr(context, '_room_name'):
        room_name = context._room_name
    # Fallback: try to get room from any available attribute
    else:
        room_obj = getattr(context, 'room', None)
        if room_obj and hasattr(room_obj, 'name'):
            room_name = room_obj.name
    
    # Generate consistent UUID based on room name (same room = same session)
    session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, room_name))
    logging.info(f"Generated session ID: {session_id} for room: '{room_name}' (context type: {type(context).__name__})")
    
    return session_id