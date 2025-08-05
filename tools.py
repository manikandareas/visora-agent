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
from supabase import Client, create_client

load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

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

@function_tool()
async def control_camera(
    context: RunContext,
    action: str,
    camera_type: str = "user"
) -> str:
    """
    Control camera state (on/off/switch) and update database.
    
    Args:
        action: "on", "off", or "switch"
        camera_type: "user" (front) or "environment" (back)
    """
    try:
        # Get consistent session ID
        session_id = get_session_id(context)
        
        if not session_id:
            return "Session tidak ditemukan. Silakan mulai sesi baru."
        
        # Check if session exists in database, create if it doesn't
        try:
            existing_session = supabase.table("sessions").select("id").eq("id", session_id).execute()
            if not existing_session.data:
                # Session doesn't exist, create it
                logging.info(f"Session {session_id} not found, creating it...")
                import uuid as uuid_lib
                session_token = str(uuid_lib.uuid4())
                
                supabase.table("sessions").insert({
                    "id": session_id,
                    "user_id": f"user_auto_created",
                    "session_token": session_token,
                    "is_active": True,
                    "updated_at": "NOW()"
                }).execute()
                
                logging.info(f"Auto-created session {session_id}")
        except Exception as session_check_error:
            logging.error(f"Error checking/creating session: {session_check_error}")
        
        if action == "on":
            # Update camera state to enabled
            result = supabase.table("camera_states").upsert({
                "session_id": session_id,
                "is_enabled": True,
                "camera_type": camera_type,
                "updated_at": "NOW()"
            }, on_conflict="session_id").execute()
            
            logging.info(f"Camera turned on for session {session_id}")
            return "Kamera telah diaktifkan dan siap digunakan."
            
        elif action == "off":
            # Update camera state to disabled
            result = supabase.table("camera_states").upsert({
                "session_id": session_id,
                "is_enabled": False,
                "camera_type": camera_type,
                "updated_at": "NOW()"
            }, on_conflict="session_id").execute()
            
            logging.info(f"Camera turned off for session {session_id}")
            return "Kamera telah dimatikan."
            
        elif action == "switch":
            # Get current camera state
            current_state = supabase.table("camera_states").select("camera_type").eq("session_id", session_id).execute()

            logging.info(f"Current camera state for session {session_id}: {current_state.data}")
            
            new_camera_type = "environment" if current_state.data and current_state.data[0]["camera_type"] == "user" else "user"
            
            # Update camera type
            result = supabase.table("camera_states").upsert({
                "session_id": session_id,
                "is_enabled": True,
                "camera_type": new_camera_type,
                "updated_at": "NOW()"
            }, on_conflict="session_id").execute()
            
            camera_name = "kamera belakang" if new_camera_type == "environment" else "kamera depan"
            logging.info(f"Camera switched to {new_camera_type} for session {session_id}")
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
async def create_session(
    context: RunContext,
    user_id: str
) -> str:
    """
    Create a new user session in the database using participant identity.
    """
    try:
        # Get consistent session ID (same as control_camera)
        session_id = get_session_id(context)
        
        if not session_id:
            return "Tidak dapat membuat sesi. Room tidak ditemukan."
        
        # Store user session info (matching actual schema)
        import uuid as uuid_lib
        session_token = str(uuid_lib.uuid4())
        
        result = supabase.table("sessions").upsert({
            "id": session_id,
            "user_id": user_id,
            "session_token": session_token,
            "is_active": True,
            "updated_at": "NOW()"
        }).execute()
        
        # Initialize camera state
        supabase.table("camera_states").upsert({
            "session_id": session_id,
            "is_enabled": False,
            "camera_type": "user",
            "updated_at": "NOW()"
        }).execute()
        
        logging.info(f"Session created/updated for participant: {session_id}")
        return f"Sesi telah dibuat untuk pengguna: {user_id}"
        
    except Exception as e:
        logging.error(f"Error creating session: {e}")
        return "Terjadi kesalahan saat membuat sesi baru."

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
        logging.error(f"Error sending email: {e}")
        return f"An error occurred while sending email: {str(e)}"
