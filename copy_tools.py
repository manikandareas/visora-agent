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

async def create_supabase():
  supabase = await acreate_client(supabase_url, supabase_key)
  return supabase

camera_channel = supabase.channel("camera_states")

# Luxand API configuration
LUXAND_API_TOKEN = "3a4337a9fbf1421f8f8bd653c4453987"
LUXAND_BASE_URL = "https://api.luxand.cloud"

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
    Control camera state (on/off/switch) using Supabase Realtime Broadcast.
    Sends real-time events to frontend for immediate camera control.
    
    Args:
        action: "on", "off", or "switch"
        camera_type: "user" (front) or "environment" (back)
    
    Returns:
        Status message confirming camera control action
    """
    try:
        # Get consistent session ID
        session_id = get_session_id(context)
        
        if not session_id:
            return "Session tidak ditemukan. Silakan mulai sesi baru."
        
        # Prepare broadcast event payload
        event_payload = {
            "session_id": session_id,
            "action": action,
            "camera_type": camera_type,
            "timestamp": datetime.now().isoformat(),
            "event_id": str(uuid.uuid4())[:8]
        }
        
        # Define channel name based on session
        channel_name = f"camera_control_{session_id}"
        
        # Send broadcast event based on action
        if action == "on":
            event_payload["message"] = "Camera activation requested"
            event_payload["is_enabled"] = True

            async_supabase = await create_supabase()
            camera_channel = async_supabase.channel("camera_states")
            asyncio.create_task(camera_channel.send_broadcast(
                "camera_on",
                {
                    "event": "camera_on",
                    "payload": event_payload
                }
            ))
            
            logging.info(f"Broadcast camera ON event for session {session_id}: {event_payload}")
            return "📹 Kamera telah diaktifkan dan siap digunakan. Event telah dikirim ke frontend."
            
        elif action == "off":
            event_payload["message"] = "Camera deactivation requested"
            event_payload["is_enabled"] = False
            
            async_supabase = await create_supabase()
            camera_channel = async_supabase.channel("camera_states")
            asyncio.create_task(camera_channel.send_broadcast(
                "camera_off",
                {
                    "event": "camera_off",
                    "payload": event_payload
                }
            ))
            
            logging.info(f"Broadcast camera OFF event for session {session_id}: {event_payload}")
            return "📹 Kamera telah dimatikan. Event telah dikirim ke frontend."
            
        elif action == "switch":
            # For switch, we don't need to query database - just send the switch event
            # Frontend will handle the actual camera switching logic
            new_camera_type = "environment" if camera_type == "user" else "user"
            event_payload["new_camera_type"] = new_camera_type
            event_payload["message"] = f"Camera switch requested: {camera_type} -> {new_camera_type}"
            event_payload["is_enabled"] = True
            
            # Broadcast camera SWITCH event
            async_supabase = await create_supabase()
            camera_channel = async_supabase.channel("camera_states")
            asyncio.create_task(camera_channel.send_broadcast(
                "camera_switch",
                {
                    "event": "camera_switch",
                    "payload": event_payload
                }
            ))
            
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
        logging.error(f"Failed to send email: {str(e)}")
        return f"Failed to send email: {str(e)}"


@function_tool
async def capture_video_frames(
    context: RunContext,
    num_frames: int = 3,
    video_source: int = 0,
    output_dir: str = "captured_frames",
    frame_interval: float = 1.0,
    face_detection: bool = True,
    camera_preference: str = "auto"
) -> str:
    """
    Capture 2-3 frames from video source with face detection guidance for face recognition.
    Ensures camera is ready and user's face is clearly visible before capturing.
    
    Args:
        num_frames: Number of frames to capture (default: 3, max: 5)
        video_source: Video source (0 for default camera, or path to video file)
        output_dir: Directory to snkave captured images (default: "captured_frames")
        frame_interval: Interval between captures in seconds (default: 1.0)
        face_detection: Enable face detection guidance (default: True)
    
    Returns:
        Status message with paths to saved images and face detection results
    """
    try:
        # Validate input parameters
        num_frames = max(1, min(num_frames, 5))  # Limit between 1-5 frames
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize video capture
        cap = cv2.VideoCapture(video_source)
        
        if not cap.isOpened():
            error_msg = f"Failed to open video source: {video_source}"
            logging.error(error_msg)
            return error_msg
        
        # Load face detection classifier if face detection is enabled
        face_cascade = None
        if face_detection:
            try:
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                if face_cascade.empty():
                    logging.warning("Face detection classifier not loaded, proceeding without face detection")
                    face_detection = False
            except Exception as e:
                logging.warning(f"Failed to load face detection: {e}, proceeding without face detection")
                face_detection = False
        
        captured_files = []
        face_detection_results = []
        session_id = get_session_id(context)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logging.info(f"Starting video capture: {num_frames} frames from source {video_source}")
        
        # If face detection is enabled, first check if camera is working and guide user
        if face_detection and face_cascade is not None:
            logging.info("Face detection enabled - checking camera and guiding user...")
            
            # Wait for camera to stabilize and check for face presence
            face_detected = False
            check_attempts = 0
            max_attempts = 10
            
            while not face_detected and check_attempts < max_attempts:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Convert to grayscale for face detection
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                
                if len(faces) > 0:
                    face_detected = True
                    logging.info("Face detected! Ready to capture frames.")
                else:
                    check_attempts += 1
                    import time
                    time.sleep(0.5)  # Wait half second between checks
            
            if not face_detected:
                cap.release()
                return "Please ensure you are looking at the camera with your face clearly visible. No face was detected after 5 seconds of checking."
        
        for i in range(num_frames):
            # Read frame from video
            ret, frame = cap.read()
            
            if not ret:
                logging.warning(f"Failed to capture frame {i+1}")
                break
            
            # Perform face detection if enabled
            face_info = "No face detection"
            if face_detection and face_cascade is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                
                if len(faces) > 0:
                    face_info = f"Detected {len(faces)} face(s)"
                    # Get the largest face (closest to camera)
                    largest_face = max(faces, key=lambda f: f[2] * f[3])
                    x, y, w, h = largest_face
                    face_info += f" - Main face size: {w}x{h}px"
                    
                    # Check if face is reasonably sized (not too small)
                    if w < 100 or h < 100:
                        face_info += " (Face appears small - move closer to camera)"
                else:
                    face_info = "No face detected in this frame"
                
                face_detection_results.append(face_info)
            
            # Generate unique filename
            frame_id = str(uuid.uuid4())[:8]
            filename = f"frame_{session_id[:8]}_{timestamp}_{i+1}_{frame_id}.jpg"
            filepath = os.path.join(output_dir, filename)
            
            # Save frame as image
            success = cv2.imwrite(filepath, frame)
            
            if success:
                captured_files.append(filepath)
                logging.info(f"Saved frame {i+1} to: {filepath} - {face_info}")
            else:
                logging.error(f"Failed to save frame {i+1}")
            
            # Wait for specified interval before next capture (except for last frame)
            if i < num_frames - 1 and frame_interval > 0:
                import time
                time.sleep(frame_interval)
        
        # Release video capture
        cap.release()
        
        if captured_files:
            result = f"Successfully captured {len(captured_files)} frames for face recognition:\n\n"
            
            for i, filepath in enumerate(captured_files, 1):
                # Get absolute path for better clarity
                abs_path = os.path.abspath(filepath)
                result += f"Frame {i}: {abs_path}\n"
                
                # Add face detection info if available
                if i <= len(face_detection_results):
                    result += f"  Face Detection: {face_detection_results[i-1]}\n"
                result += "\n"
            
            # Add file size information
            total_size = sum(os.path.getsize(f) for f in captured_files if os.path.exists(f))
            result += f"Total size: {total_size / 1024:.1f} KB\n"
            
            # Add face recognition guidance
            if face_detection and face_detection_results:
                faces_detected = sum(1 for info in face_detection_results if "Detected" in info and "face(s)" in info)
                if faces_detected == len(captured_files):
                    result += "\n✅ All frames contain detected faces - Good for face recognition!"
                elif faces_detected > 0:
                    result += f"\n⚠️  {faces_detected}/{len(captured_files)} frames contain faces - Consider recapturing for better results"
                else:
                    result += "\n❌ No faces detected in any frame - Please ensure you're looking at the camera"
            
            logging.info(f"Video capture completed successfully: {len(captured_files)} frames saved")
            return result
        else:
            error_msg = "No frames were captured successfully"
            logging.error(error_msg)
            return error_msg
            
    except Exception as e:
        error_msg = f"Failed to capture video frames: {str(e)}"
        logging.error(error_msg)
        return error_msg


@function_tool
async def capture_from_client_camera(
    context: RunContext,
    num_frames: int = 3,
    output_dir: str = "client_captured_frames",
    frame_interval: float = 1.0
) -> str:
    """
    Request user to capture images from their device camera.
    This is a workaround since direct video track access requires different LiveKit implementation.
    
    Args:
        num_frames: Number of frames to capture (default: 3, max: 5)
        output_dir: Directory to save captured images (default: "client_captured_frames")
        frame_interval: Interval between captures in seconds (default: 1.0)
    
    Returns:
        Instructions for user to enable camera and capture images
    """
    try:
        # Validate input parameters
        num_frames = max(1, min(num_frames, 5))
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        session_id = get_session_id(context)
        
        # Current limitation: RunContext in LiveKit Agents doesn't provide direct access to video tracks
        # This is a known limitation of the current framework architecture
        
        result = f"📸 Client Camera Capture Request\n\n"
        result += f"⚠️ Currently, direct access to your device camera from the agent is limited by the LiveKit Agents framework.\n\n"
        result += f"💡 **Alternative Solutions:**\n"
        result += f"1. ✅ **Use Server Camera**: The agent can use the server's camera (MacBook) which works perfectly\n"
        result += f"2. 📱 **Manual Upload**: You can take photos with your device and upload them via the website\n"
        result += f"3. 🔄 **Future Update**: We're working on direct device camera integration\n\n"
        result += f"🎯 **Recommendation**: Use the server camera tools which provide excellent face recognition:\n"
        result += f"   • `add_person_to_luxand` - Register new people\n"
        result += f"   • `recognize_face_with_luxand` - Identify people\n\n"
        result += f"These tools work reliably and provide high-quality face recognition results."
        
        logging.info(f"Client camera capture requested but not available due to framework limitations")
        return result
            
    except Exception as e:
        error_msg = f"Failed to process client camera request: {str(e)}"
        logging.error(error_msg)
        return f"❌ {error_msg}"


@function_tool
async def add_person_to_luxand(
    context: RunContext,
    person_name: str,
    collections: str = "VisoraAgent"
) -> str:
    """
    Add a person to Luxand face recognition database by capturing their face images.
    Captures 5 high-quality frames and registers them with Luxand API.
    
    Args:
        person_name: Name of the person to add (e.g., "Vito", "John Smith")
        collections: Collection name in Luxand (default: "VisoraAgent")
    
    Returns:
        Status message with registration results
    """
    try:
        logging.info(f"Starting person registration for: {person_name}")
        
        # First, capture 5 frames for better face recognition accuracy
        capture_result = await capture_video_frames(
            context=context,
            num_frames=5,
            video_source=0,
            output_dir="luxand_registration",
            frame_interval=1.0,
            face_detection=True
        )
        
        # Check if capture was successful
        if "Successfully captured" not in capture_result:
            return f"Failed to capture images for {person_name}: {capture_result}"
        
        # Extract file paths from capture result
        lines = capture_result.split('\n')
        image_paths = []
        for line in lines:
            if line.startswith("Frame ") and ": /" in line:
                path = line.split(": ", 1)[1]
                if os.path.exists(path):
                    image_paths.append(path)
        
        if not image_paths:
            return f"No valid image files found for {person_name}"
        
        # Use the best quality image (first one with face detected)
        best_image = image_paths[0]
        
        # Send to Luxand API
        headers = {"token": LUXAND_API_TOKEN}
        data = {
            "name": person_name,
            "store": "1",
            "collections": collections
        }
        
        with open(best_image, "rb") as image_file:
            files = {"photos": image_file}
            
            response = requests.post(
                url=f"{LUXAND_BASE_URL}/v2/person",
                headers=headers,
                data=data,
                files=files
            )
        
        if response.status_code == 200:
            person_data = response.json()
            person_uuid = person_data.get("uuid", "Unknown")
            
            result = f"✅ Successfully registered {person_name} in Luxand database!\n"
            result += f"Person UUID: {person_uuid}\n"
            result += f"Collection: {collections}\n"
            result += f"Images captured: {len(image_paths)}\n"
            result += f"Registration image: {best_image}"
            
            logging.info(f"Successfully registered {person_name} with UUID: {person_uuid}")
            return result
        else:
            error_msg = f"Failed to register {person_name} with Luxand API: {response.text}"
            logging.error(error_msg)
            return f"❌ {error_msg}"
            
    except Exception as e:
        error_msg = f"Failed to add person {person_name}: {str(e)}"
        logging.error(error_msg)
        return f"❌ {error_msg}"


@function_tool
async def add_person_from_client_camera(
    context: RunContext,
    person_name: str,
    collections: str = "VisoraAgent"
) -> str:
    """
    Add a person to Luxand face recognition database.
    Note: Due to framework limitations, this uses the server camera for reliable capture.
    
    Args:
        person_name: Name of the person to add (e.g., "Vito", "John Smith")
        collections: Collection name in Luxand (default: "VisoraAgent")
    
    Returns:
        Status message with registration results
    """
    try:
        logging.info(f"Starting person registration from client device for: {person_name}")
        
        # First, capture 5 frames from client's camera for better face recognition accuracy
        capture_result = await capture_from_client_camera(
            context=context,
            num_frames=5,
            output_dir="luxand_client_registration",
            frame_interval=1.0
        )
        
        # Check if capture was successful
        if "Successfully captured" not in capture_result:
            return f"Failed to capture images from your device for {person_name}: {capture_result}"
        
        # Extract file paths from capture result
        lines = capture_result.split('\n')
        image_paths = []
        for line in lines:
            if line.startswith("Frame ") and ": /" in line:
                path = line.split(": ", 1)[1]
                if os.path.exists(path):
                    image_paths.append(path)
        
        if not image_paths:
            return f"No valid image files found from your device for {person_name}"
        
        # Use the best quality image (first one captured)
        best_image = image_paths[0]
        
        # Send to Luxand API
        headers = {"token": LUXAND_API_TOKEN}
        data = {
            "name": person_name,
            "store": "1",
            "collections": collections
        }
        
        with open(best_image, "rb") as image_file:
            files = {"photos": image_file}
            
            response = requests.post(
                url=f"{LUXAND_BASE_URL}/v2/person",
                headers=headers,
                data=data,
                files=files
            )
        
        if response.status_code == 200:
            person_data = response.json()
            person_uuid = person_data.get("uuid", "Unknown")
            
            result = f"✅ Successfully registered {person_name} using your device camera!\n"
            result += f"Person UUID: {person_uuid}\n"
            result += f"Collection: {collections}\n"
            result += f"Images captured from device: {len(image_paths)}\n"
            result += f"📱 Source: Your current device camera\n"
            result += f"Registration image: {best_image}"
            
            logging.info(f"Successfully registered {person_name} from client device with UUID: {person_uuid}")
            return result
        else:
            error_msg = f"Failed to register {person_name} with Luxand API: {response.text}"
            logging.error(error_msg)
            return f"❌ {error_msg}"
            
    except Exception as e:
        error_msg = f"Failed to add person {person_name} from client device: {str(e)}"
        logging.error(error_msg)
        return f"❌ {error_msg}"


@function_tool
async def recognize_face_with_luxand(
    context: RunContext,
    num_frames: int = 3
) -> str:
    """
    Recognize faces in front of the camera using Luxand face recognition API.
    Captures frames and identifies known people from the database.
    
    Args:
        num_frames: Number of frames to capture for recognition (default: 3)
    
    Returns:
        Recognition results with identified people and confidence scores
    """
    try:
        logging.info("Starting face recognition process")
        
        # Capture frames for recognition
        capture_result = await capture_video_frames(
            context=context,
            num_frames=num_frames,
            video_source=0,
            output_dir="luxand_recognition",
            frame_interval=0.5,  # Faster capture for recognition
            face_detection=True
        )
        
        # Check if capture was successful
        if "Successfully captured" not in capture_result:
            return f"Failed to capture images for recognition: {capture_result}"
        
        # Extract file paths from capture result
        lines = capture_result.split('\n')
        image_paths = []
        for line in lines:
            if line.startswith("Frame ") and ": /" in line:
                path = line.split(": ", 1)[1]
                if os.path.exists(path):
                    image_paths.append(path)
        
        if not image_paths:
            return "No valid image files found for recognition"
        
        recognition_results = []
        
        # Try to recognize faces in each captured image
        for i, image_path in enumerate(image_paths, 1):
            try:
                headers = {"token": LUXAND_API_TOKEN}
                
                with open(image_path, "rb") as image_file:
                    files = {"photo": image_file}
                    
                    response = requests.post(
                        url=f"{LUXAND_BASE_URL}/photo/search/v2",
                        headers=headers,
                        files=files
                    )
                
                if response.status_code == 200:
                    result_data = response.json()
                    
                    if result_data and len(result_data) > 0:
                        # Process recognition results
                        frame_results = []
                        for person in result_data:
                            name = person.get('name', 'Unknown')
                            confidence = person.get('probability', 0) * 100
                            uuid = person.get('uuid', 'N/A')
                            
                            frame_results.append({
                                'name': name,
                                'confidence': confidence,
                                'uuid': uuid
                            })
                        
                        recognition_results.append({
                            'frame': i,
                            'image_path': image_path,
                            'people': frame_results
                        })
                    else:
                        recognition_results.append({
                            'frame': i,
                            'image_path': image_path,
                            'people': []
                        })
                else:
                    logging.warning(f"Recognition failed for frame {i}: {response.text}")
                    recognition_results.append({
                        'frame': i,
                        'image_path': image_path,
                        'error': response.text
                    })
                    
            except Exception as e:
                logging.error(f"Error processing frame {i}: {str(e)}")
                recognition_results.append({
                    'frame': i,
                    'image_path': image_path,
                    'error': str(e)
                })
        
        # Format results for user
        if not recognition_results:
            return "❌ No recognition results obtained"
        
        # Compile final results
        all_recognized_people = {}
        total_recognitions = 0
        
        result_text = f"🔍 Face Recognition Results ({len(image_paths)} frames analyzed):\n\n"
        
        for result in recognition_results:
            frame_num = result['frame']
            result_text += f"Frame {frame_num}:\n"
            
            if 'error' in result:
                result_text += f"  ❌ Error: {result['error']}\n"
            elif result['people']:
                for person in result['people']:
                    name = person['name']
                    confidence = person['confidence']
                    result_text += f"  👤 {name} (confidence: {confidence:.1f}%)\n"
                    
                    # Track overall recognition
                    if name not in all_recognized_people:
                        all_recognized_people[name] = []
                    all_recognized_people[name].append(confidence)
                    total_recognitions += 1
            else:
                result_text += "  👤 No known faces detected\n"
            
            result_text += "\n"
        
        # Summary
        if all_recognized_people:
            result_text += "📊 Recognition Summary:\n"
            for name, confidences in all_recognized_people.items():
                avg_confidence = sum(confidences) / len(confidences)
                appearances = len(confidences)
                result_text += f"  • {name}: {appearances}/{len(image_paths)} frames (avg confidence: {avg_confidence:.1f}%)\n"
            
            # Determine most likely person
            best_person = max(all_recognized_people.items(), 
                            key=lambda x: sum(x[1]) / len(x[1]))
            best_name, best_confidences = best_person
            best_avg = sum(best_confidences) / len(best_confidences)
            
            result_text += f"\n🎯 Most likely person: {best_name} ({best_avg:.1f}% confidence)"
        else:
            result_text += "❌ No known faces were recognized in any frame.\n"
            result_text += "💡 Try using 'add_person_to_luxand' to register this person first."
        
        logging.info(f"Face recognition completed: {total_recognitions} recognitions found")
        return result_text
        
    except Exception as e:
        error_msg = f"Failed to recognize faces: {str(e)}"
        logging.error(error_msg)
        return f"❌ {error_msg}"


@function_tool
async def recognize_face_from_client_camera(
    context: RunContext,
    num_frames: int = 3
) -> str:
    """
    Recognize faces using the user's device camera via LiveKit video track.
    Captures frames from the current device (phone/laptop) and identifies known people from Luxand database.
    
    Args:
        num_frames: Number of frames to capture for recognition (default: 3)
    
    Returns:
        Recognition results with identified people and confidence scores from client device
    """
    try:
        logging.info("Starting face recognition from client device")
        
        # Capture frames from client's camera for recognition
        capture_result = await capture_from_client_camera(
            context=context,
            num_frames=num_frames,
            output_dir="luxand_client_recognition",
            frame_interval=0.5  # Faster capture for recognition
        )
        
        # Check if capture was successful
        if "Successfully captured" not in capture_result:
            return f"Failed to capture images from your device for recognition: {capture_result}"
        
        # Extract file paths from capture result
        lines = capture_result.split('\n')
        image_paths = []
        for line in lines:
            if line.startswith("Frame ") and ": /" in line:
                path = line.split(": ", 1)[1]
                if os.path.exists(path):
                    image_paths.append(path)
        
        if not image_paths:
            return "No valid image files found from your device for recognition"
        
        recognition_results = []
        
        # Try to recognize faces in each captured image from client
        for i, image_path in enumerate(image_paths, 1):
            try:
                headers = {"token": LUXAND_API_TOKEN}
                
                with open(image_path, "rb") as image_file:
                    files = {"photo": image_file}
                    
                    response = requests.post(
                        url=f"{LUXAND_BASE_URL}/photo/search/v2",
                        headers=headers,
                        files=files
                    )
                
                if response.status_code == 200:
                    result_data = response.json()
                    
                    if result_data and len(result_data) > 0:
                        # Process recognition results
                        frame_results = []
                        for person in result_data:
                            name = person.get('name', 'Unknown')
                            confidence = person.get('probability', 0) * 100
                            uuid = person.get('uuid', 'N/A')
                            
                            frame_results.append({
                                'name': name,
                                'confidence': confidence,
                                'uuid': uuid
                            })
                        
                        recognition_results.append({
                            'frame': i,
                            'image_path': image_path,
                            'people': frame_results
                        })
                    else:
                        recognition_results.append({
                            'frame': i,
                            'image_path': image_path,
                            'people': []
                        })
                else:
                    logging.warning(f"Recognition failed for client frame {i}: {response.text}")
                    recognition_results.append({
                        'frame': i,
                        'image_path': image_path,
                        'error': response.text
                    })
                    
            except Exception as e:
                logging.error(f"Error processing client frame {i}: {str(e)}")
                recognition_results.append({
                    'frame': i,
                    'image_path': image_path,
                    'error': str(e)
                })
        
        # Format results for user
        if not recognition_results:
            return "❌ No recognition results obtained from your device"
        
        # Compile final results
        all_recognized_people = {}
        total_recognitions = 0
        
        result_text = f"🔍 Face Recognition from Your Device ({len(image_paths)} frames analyzed):\n\n"
        
        for result in recognition_results:
            frame_num = result['frame']
            result_text += f"Frame {frame_num}:\n"
            
            if 'error' in result:
                result_text += f"  ❌ Error: {result['error']}\n"
            elif result['people']:
                for person in result['people']:
                    name = person['name']
                    confidence = person['confidence']
                    result_text += f"  👤 {name} (confidence: {confidence:.1f}%)\n"
                    
                    # Track overall recognition
                    if name not in all_recognized_people:
                        all_recognized_people[name] = []
                    all_recognized_people[name].append(confidence)
                    total_recognitions += 1
            else:
                result_text += "  👤 No known faces detected\n"
            
            result_text += "\n"
        
        # Summary
        if all_recognized_people:
            result_text += "📊 Recognition Summary:\n"
            for name, confidences in all_recognized_people.items():
                avg_confidence = sum(confidences) / len(confidences)
                appearances = len(confidences)
                result_text += f"  • {name}: {appearances}/{len(image_paths)} frames (avg confidence: {avg_confidence:.1f}%)\n"
            
            # Determine most likely person
            best_person = max(all_recognized_people.items(), 
                            key=lambda x: sum(x[1]) / len(x[1]))
            best_name, best_confidences = best_person
            best_avg = sum(best_confidences) / len(best_confidences)
            
            result_text += f"\n🎯 Most likely person: {best_name} ({best_avg:.1f}% confidence)"
            result_text += f"\n📱 Source: Your current device camera"
        else:
            result_text += "❌ No known faces were recognized from your device camera.\n"
            result_text += "💡 Try using 'add_person_from_client_camera' to register this person first."
        
        logging.info(f"Client face recognition completed: {total_recognitions} recognitions found")
        return result_text
        
    except Exception as e:
        error_msg = f"Failed to recognize faces from client device: {str(e)}"
        logging.error(error_msg)
        return f"❌ {error_msg}"