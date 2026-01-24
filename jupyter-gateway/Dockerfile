FROM pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl wget git build-essential \
      # for OpenCV
      libgl1 libglib2.0-0 \ 
      # for Tesseract OCR
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
      # chinese fonts
      fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt && rm /tmp/requirements.txt

EXPOSE 9888

CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.api=kernel_gateway.jupyter_websocket", "--ip=0.0.0.0", "--port=9888"]
