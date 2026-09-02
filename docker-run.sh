#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Build and run the Open WebUI Docker container locally.
# ---------------------------------------------------------------------------

# Очистка используемых портов (освобождаем только процессы, слушающие порт)
clear_port() {
  local port=$1
  if command -v fuser &> /dev/null; then
    if fuser "$port/tcp" &> /dev/null 2>&1; then
      echo "⚠️  Порт $port уже используется. Освобождаем..."
      fuser -k "$port/tcp" 2>/dev/null || echo "Не удалось освободить порт $port"
    fi
  elif command -v lsof &> /dev/null; then
    if lsof -i :"$port" &> /dev/null 2>&1; then
      echo "⚠️  Порт $port уже используется. Освобождаем..."
      local pids
      pids=$(lsof -t -i :"$port" 2>/dev/null || true)
      if [[ -n "$pids" ]]; then
        kill $pids 2>/dev/null || echo "Не удалось освободить порт $port"
      fi
    fi
  fi
}

readonly IMAGE="open-webui"
readonly CONTAINER="open-webui"
readonly VOLUME="open-webui-rus_open-webui"
readonly HOST_PORT="${OPEN_WEBUI_PORT:-8083}"
readonly CONTAINER_PORT=8080

# Освобождение имени контейнера (docker run не перезаписывает существующее имя)
if docker inspect "$CONTAINER" &>/dev/null; then
  echo "⚠️  Контейнер ${CONTAINER} уже существует. Удаляем..."
  docker rm -f "$CONTAINER" 2>/dev/null || echo "Не удалось удалить контейнер ${CONTAINER}"
fi

clear_port "$HOST_PORT"

echo "========================================="
echo "Open WebUI Docker Runner"
echo "========================================="

echo "🔨 Сборка образа ${IMAGE}..."
if ! docker build -t "$IMAGE" .; then
    echo "❌ Ошибка сборки образа"
    exit 1
fi

echo "💾 Создание тома данных ${VOLUME}..."
docker volume create "$VOLUME" 2>/dev/null || echo "Том ${VOLUME} уже существует"

echo "🚀 Запуск контейнера ${CONTAINER}..."
if ! docker run -d \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  --add-host=host.docker.internal:host-gateway \
  -v "${VOLUME}:/app/backend/data" \
  --name "$CONTAINER" \
  --restart always \
  "$IMAGE"; then
    echo "❌ Ошибка запуска контейнера"
    exit 1
fi

echo "✅ Open WebUI запущен!"
echo ""
echo "🌐 Доступен по адресу: http://localhost:${HOST_PORT}"
echo "📁 Данные сохраняются в томе: ${VOLUME}"
echo ""
echo "📋 Полезные команды:"
echo "   docker logs ${CONTAINER}        - просмотр логов"
echo "   docker exec -it ${CONTAINER} bash - войти в контейнер"
echo "   docker stop ${CONTAINER}        - остановить контейнер"
echo "   docker start ${CONTAINER}       - запустить контейнер"
echo "========================================="
