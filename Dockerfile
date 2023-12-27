FROM python:3.10-slim

WORKDIR /usr/src/fireblocks
COPY signer.py .env requirements.txt /usr/src/fireblocks/
COPY templates /usr/src/fireblocks/templates

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

ENV APPLICATION_ENVIRONMENT=test

CMD ["python", "signer.py"]