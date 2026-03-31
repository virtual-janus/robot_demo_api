from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import jwt, JWTError
from pydantic import BaseModel
from typing import Any, Dict
from contextlib import asynccontextmanager
import uuid
import httpx
import traceback
import paho.mqtt.client as mqtt
import os
import asyncio
import json
from typing import Dict

# ----------------------------
# Keycloak Configuration
# ----------------------------

KEYCLOAK_SERVER = "<auth server uri here>"
REALM = "<auth server realm here>"
CLIENT_ID = "<auth server client id here>"

ISSUER = f"{KEYCLOAK_SERVER}/realms/{REALM}"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"

AUTH_URL = f"{ISSUER}/protocol/openid-connect/auth"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"

# OAuth scheme for Swagger
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=AUTH_URL,
    tokenUrl=TOKEN_URL,
)

# ----------------------------
# MQTT Setup
# ----------------------------
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "<default broker uri here>")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 8883))

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

# Use for TCP connection
mqtt_client.tls_set()
mqtt_client.tls_insecure_set(True)

def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker:", rc)

#def on_message(client, userdata, msg):
#    global event_loop
#
#    print(f"MQTT message received: {msg.topic} -> {msg.payload.decode()}")
#
#    try:
#        payload = msg.payload.decode()
#        data = json.loads(payload)
#
#        correlation_id = data.get("correlation_id")
#        response_payload = data.get("payload")
#
#        if correlation_id in pending_responses:
#            future = pending_responses.pop(correlation_id)
#
#            if not future.done():
#                if event_loop is not None:
#                    event_loop.call_soon_threadsafe(
#                        future.set_result,
#                        response_payload
#                    )
#                else:
#                    print("⚠️ Event loop not initialized yet")
#
#    except Exception as e:
#        print("MQTT message handling error:", str(e))

def on_message(client, userdata, msg):
    global event_loop, pending_future

    print(f"MQTT message received: {msg.topic} -> {msg.payload.decode()}")

    try:
        payload = msg.payload.decode()

        if pending_future and not pending_future.done():
            if event_loop is not None:
                event_loop.call_soon_threadsafe(
                    pending_future.set_result,
                    payload
                )
            else:
                print("⚠️ Event loop not initialized yet")

    except Exception as e:
        print("MQTT message handling error:", str(e))

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# Correlation isn't supported by the Matlan API wrapper
#pending_responses: Dict[str, asyncio.Future] = {}
pending_future: asyncio.Future | None = None

event_loop: asyncio.AbstractEventLoop | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global event_loop

    # ✅ Get loop FIRST
    event_loop = asyncio.get_running_loop()
    mqtt_client.loop = event_loop

    print("Event loop initialized:", event_loop)

    # ✅ THEN start MQTT
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
    print("MQTT client started")

    yield

    # Shutdown
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    print("MQTT client stopped")

# ----------------------------
# FastAPI App
# ----------------------------

app = FastAPI(
    title="Robot Demo - Front-End API",
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_init_oauth={
        "clientId": CLIENT_ID,
        "usePkceWithAuthorizationCodeGrant": True,
    },
)

# ----------------------------
# Data Models
# ----------------------------

class CommandRequest(BaseModel):
    command: str
    payload: Dict[str, Any]

class SubscribeRequest(BaseModel):
    topic: str

class PublishRequest(BaseModel):
    topic: str
    message: str

class SystemStateRequest(BaseModel):
    topic: str
    targetState: str

class InvokeRequest(BaseModel):
    topicPublish: str
    topicSubscribe: str
    message: str

# ----------------------------
# JWKS Cache
# ----------------------------

jwks_cache = None

async def get_jwks():
    global jwks_cache
    if jwks_cache is None:
        async with httpx.AsyncClient() as client:
            response = await client.get(JWKS_URL)
            jwks_cache = response.json()
    return jwks_cache

# ----------------------------
# Token Validation
# ----------------------------

async def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        jwks = await get_jwks()

        header = jwt.get_unverified_header(token)

        key = None
        for jwk in jwks["keys"]:
            if jwk["kid"] == header["kid"]:
                key = jwk

        if key is None:
            raise HTTPException(status_code=401, detail="Invalid token key")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False}
        )

        return payload
    
    except JWTError as e:
        print("JWT ERROR:", str(e))   
        raise HTTPException(
            status_code=401,
            detail=f"JWT validation error: {str(e)}"
        )

    except Exception as e:
        print("TOKEN ERROR TYPE:", type(e))
        print("TOKEN ERROR REPR:", repr(e))
        print("TRACEBACK:")
        traceback.print_exc()

        raise HTTPException(
            status_code=401,
            detail="Token validation failed"
        )

# ----------------------------
# Routes
# ----------------------------

@app.get("/")
def read_root():
    return {"message": "Hello from the API!"}


@app.get("/secure")
async def secure_endpoint(user=Depends(verify_token)):
    return {
        "message": "You are authenticated",
        "user": user["preferred_username"]
    }


@app.post("/command")
async def run_command(
    cmd: CommandRequest,
    user=Depends(verify_token)
):
    command_id = str(uuid.uuid4())

    payload_with_id = cmd.payload.copy()
    payload_with_id["command_id"] = command_id

    return {
        "message": "Command received",
        "user": user["preferred_username"],
        "command": cmd.command,
        "payload": payload_with_id
    }

#@app.post("/mqtt/subscribe")
#def subscribe_topic(req: SubscribeRequest):
#    print(f"MQTT subscribe: {req.topic}")
#    mqtt_client.subscribe(req.topic)
#
#    return {
#        "message": "Subscribed successfully",
#        "topic": req.topic
#    }

@app.post("/mqtt/publish")
def publish_message(req: PublishRequest, user=Depends(verify_token)):
    # Publish the message
    print(f"MQTT publish: {req.topic} -> {req.message}")
    result = mqtt_client.publish(req.topic, req.message)

    # result: (rc, mid)
    rc, mid = result
    if rc != 0:
        return {"message": "Failed to publish", "rc": rc}
    
    return {
        "message": "Published successfully",
        "topic": req.topic,
        "payload": req.message
    }

@app.post("/mqtt/systemstate")
def set_system_state(req: SystemStateRequest, user=Depends(verify_token)):
    # Validate
    allowed_values = ("real", "synthetic")  # only these are valid

    if req.targetState not in allowed_values:
        return {"message": "Invalid target state"}

    # Create the payload
    payload = {
        "payload": {
            "targetState": req.targetState
        }
    }

    print(f"MQTT publish systemstate: {req.topic} -> {payload}")
    payload_str = json.dumps(payload)
    result = mqtt_client.publish(req.topic, payload_str)

    rc, mid = result
    if rc != 0:
        return {"message": "Failed to publish", "rc": rc}
    
    return {
        "message": "Published successfully",
        "topic": req.topic,
        "payload": req.targetState
    }

@app.post("/invoke")
async def invoke(req: InvokeRequest, user=Depends(verify_token)):
    global pending_future

    loop = asyncio.get_running_loop()

    # 🚫 Prevent concurrent calls
    if pending_future and not pending_future.done():
        return {
            "message": "Another invoke is already in progress"
        }

    future = loop.create_future()
    pending_future = future

    mqtt_client.subscribe(req.topicSubscribe, qos=1)

    print(f"Invoke publish: {req.topicPublish} -> {req.message}")

    rc, mid = mqtt_client.publish(req.topicPublish, req.message)

    if rc != 0:
        pending_future = None
        return {"message": "Failed to publish", "rc": rc}

    try:
        response = await asyncio.wait_for(future, timeout=10.0)

        mqtt_client.unsubscribe(req.topicSubscribe)
        pending_future = None

        return {
            "message": "Response received",
            "publish_topic": req.topicPublish,
            "subscribe_topic": req.topicSubscribe,
            "response": response
        }

    except asyncio.TimeoutError:
        pending_future = None

        return {
            "message": "Timeout waiting for response"
        }
