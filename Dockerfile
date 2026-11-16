# Imagem para rodar o monitor online (Railway, Render, Fly.io ou uma VPS com Docker).
FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Online: aceita acessos de fora, guarda o banco no disco permanente montado em /data
# e não tenta abrir navegador. PORT é definido pelo serviço de hospedagem (padrão 8765).
ENV VELL_HOST=0.0.0.0 \
    VELL_DB=/data/vell.db \
    VELL_SEM_NAVEGADOR=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8765
CMD ["python", "servidor.py"]
