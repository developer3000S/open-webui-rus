#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Build and run the Open WebUI Docker container locally.
# ---------------------------------------------------------------------------

readonly IMAGE="open-webui"
readonly CONTAINER="open-webui"
readonly VOLUME="open-webui-rus_open-webui"
readonly HOST_PORT="${OPEN_WEBUI_PORT:-8083}"
readonly CONTAINER_PORT=8080

echo "========================================="
echo "Open WebUI Docker Runner"
echo "========================================="

# Проверяем, доступен ли порт
if command -v nc &> /dev/null; then
    if nc -z localhost "$HOST_PORT" &> /dev/null; then
        echo "⚠️  Порт $HOST_PORT уже используется. Убедитесь, что нет других контейнеров Open WebUI."
    fi
fi

echo "🔨 Сборка образа ${IMAGE}..."
if ! docker build -t "$IMAGE" .; then
    echo "❌ Ошибка сборки образа"
    exit 1
fi

echo "🛑 Остановка существующего контейнера ${CONTAINER}..."
docker stop "$CONTAINER" 2>/dev/null || echo "Контейнер ${CONTAINER} не найден или уже остановлен"
docker rm "$CONTAINER" 2>/dev/null || echo "Контейнер ${CONTAINER} не найден или уже удален"

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

echo "🧹 Очистка dangling образов..."
docker image prune -f

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
