This FastAPI provides a set of endpoints to support the UKDTC Robot Demonstrator.

To run as a service, create the file /etc/systemd/system/robo-demo-api.service and populate as follows:

```
[Unit]
Description=Robot Demo API for FrontEnd
After=network.target

[Service]
User=azureuser
Group=azureuser
# Make sure these paths are correct for your environment
WorkingDirectory=/home/azureuser/robo-demo-api
ExecStart=/home/azureuser/robo-demo-api/.venv/bin/uvicorn main:app --port 8081

Environment="MQTT_USER=<set this as an environment variable>"
Environment="MQTT_PASS=<set this as an environment variable>"
Environment="MQTT_BROKER=<set this as an environment variable - the mqtt broker uri>"
Environment="MQTT_PORT=<set this as an environment variable - the MQTT broker port>"

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
