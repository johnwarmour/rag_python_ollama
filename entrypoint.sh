#!/bin/sh
set -e
# Fail on any error

echo "Starting FastAPI (8000) + Streamlit (8501) ..."
echo "Make sure to map both 8000 and 8501 ports in your Docker run/create command."

# Start FastAPI server on 8000:
cd /fastAPI
uvicorn server:app --host 0.0.0.0 --port 8000 &

# Start Streamlit app on 8501:
cd /streamlit
streamlit run app.py --server.port 8501
