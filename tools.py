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

@function_tool()
async def control_camera(
    context: RunContext,
    action: str,
    camera_type: str = "user"
) -> str:
    """
    Control camera state (on/off/switch) using Supabase Realtime Broadcast.
    Sends real-time events to frontend for immediate camera control.
    
    Args:
        action: "on", "off", or "switch"
        camera_type: "user" (front) or "environment" (back)
    
    Returns:
        Status message confirming camera control action
    """
    try:
        # Prepare broadcast event payload
        event_payload = {
            "action": action,
            "camera_type": camera_type,
            "timestamp": datetime.now().isoformat(),
            "event_id": str(uuid.uuid4())[:8]
        }

        async_supabase = await create_async_supabase()
        camera_channel = async_supabase.channel("visora_agent")

        await camera_channel.subscribe()
        
        # Send broadcast event based on action
        if action == "on":
            event_payload["message"] = "Camera activation requested"
            event_payload["is_enabled"] = True

            asyncio.create_task(camera_channel.send_broadcast(
                "camera_states",
                event_payload
            ))
            
            logging.info(f"Broadcast camera ON event: {event_payload}")
            return "📹 Kamera telah diaktifkan dan siap digunakan. Event telah dikirim ke frontend."
            
        elif action == "off":
            event_payload["message"] = "Camera deactivation requested"
            event_payload["is_enabled"] = False
            
            asyncio.create_task(camera_channel.send_broadcast(
                "camera_states",
                event_payload
            ))
            
            logging.info(f"Broadcast camera OFF event: {event_payload}")
            return "📹 Kamera telah dimatikan. Event telah dikirim ke frontend."
            
        elif action == "switch":
            # For switch, we don't need to query database - just send the switch event
            # Frontend will handle the actual camera switching logic
            new_camera_type = "environment" if camera_type == "user" else "user"
            event_payload["new_camera_type"] = new_camera_type
            event_payload["message"] = f"Camera switch requested: {camera_type} -> {new_camera_type}"
            event_payload["is_enabled"] = True
            
            # Broadcast camera SWITCH event
            asyncio.create_task(camera_channel.send_broadcast(
                "camera_states",
                event_payload
            ))
            
            camera_name = "kamera belakang" if new_camera_type == "environment" else "kamera depan"
            logging.info(f"Camera switched to {new_camera_type}")
            return f"Kamera telah diganti ke {camera_name}."
            
        else:
            return "Perintah tidak dikenali. Gunakan 'on', 'off', atau 'switch'."
            
    except Exception as e:
        logging.error(f"Error controlling camera: {e}")
        return "Terjadi kesalahan saat mengontrol kamera. Silakan coba lagi."

@function_tool()
async def get_weather(
    context: RunContext,
    city: str
) -> str:
    """
    Get the current weather for a given city with enhanced description.
    """
    try:
        response = requests.get(f"https://wttr.in/{city}?format=j1")
        if response.status_code == 200:
            data = response.json()
            current = data['current_condition'][0]
            
            # Create detailed weather description
            temp_c = current['temp_C']
            feels_like = current['FeelsLikeC']
            humidity = current['humidity']
            wind_speed = current['windspeedKmph']
            wind_dir = current['winddir16Point']
            weather_desc = current['weatherDesc'][0]['value']
            
            description = f"""
            Cuaca saat ini di {city}:
            - Suhu: {temp_c}°C (terasa seperti {feels_like}°C)
            - Kondisi: {weather_desc}
            - Kelembaban: {humidity}%
            - Angin: {wind_speed} km/jam dari arah {wind_dir}
            """
            
            logging.info(f"Weather retrieved for {city}")
            return description.strip()
        else:
            return f"Tidak dapat mengambil informasi cuaca untuk {city}."
    except Exception as e:
        logging.error(f"Error retrieving weather for {city}: {e}")
        return f"Terjadi kesalahan saat mengambil informasi cuaca untuk {city}."

@function_tool()
async def search_web(
    context: RunContext,
    query: str
) -> str:
    """
    Search the web with enhanced formatting for audio consumption.
    """
    try:
        search = DuckDuckGoSearchRun()
        results = search.run(tool_input=query)
        
        # Format results for better audio consumption
        formatted_results = f"Hasil pencarian untuk '{query}':\n\n{results}"
        
        logging.info(f"Web search completed for '{query}'")
        return formatted_results
    except Exception as e:
        logging.error(f"Error searching the web for '{query}': {e}")
        return f"Terjadi kesalahan saat mencari informasi tentang '{query}'. Silakan coba lagi."

@function_tool()    
async def send_email(
    context: RunContext,  # type: ignore
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None
) -> str:
    """
    Send an email through Gmail.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        message: Email body content
        cc_email: Optional CC email address
    """
    try:
        # Gmail SMTP configuration
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        
        # Get credentials from environment variables
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")  # Use App Password, not regular password
        
        if not gmail_user or not gmail_password:
            logging.error("Gmail credentials not found in environment variables")
            return "Email sending failed: Gmail credentials not configured."
        
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
        
        logging.info(f"Email sent successfully to {to_email}")
        return f"Email sent successfully to {to_email}"
        
    except smtplib.SMTPAuthenticationError:
        logging.error("Gmail authentication failed")
        return "Email sending failed: Authentication error. Please check your Gmail credentials."
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error occurred: {e}")
        return f"Email sending failed: SMTP error - {str(e)}"
    except Exception as e:
        logging.error(f"Failed to send email: {str(e)}")
        return f"Failed to send email: {str(e)}"




def get_session_id(context) -> str:
    """
    Generate consistent session ID based on context.
    Handles both JobContext (from agent.py) and RunContext (from tool calls).
    This ensures the same session ID is used across all functions.
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
    
    # Additional debugging - log all context attributes
    logging.debug(f"Context attributes: {[attr for attr in dir(context) if not attr.startswith('_')]}")
    if hasattr(context, 'room'):
        logging.debug(f"Room object: {context.room}, Room attributes: {[attr for attr in dir(context.room) if not attr.startswith('_')] if context.room else 'None'}")
    
    return session_id
