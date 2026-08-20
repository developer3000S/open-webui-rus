#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Быстрый запуск Open WebUI (с использованием готового образа если есть)
# ---------------------------------------------------------------------------

echo "========================================="
echo "Open WebUI Quick Start"
echo "========================================="

readonly IMAGE="open-webui"
readonly CONTAINER="open-webui"
readonly VOLUME="open-webui"
readonly HOST_PORT="${OPEN_WEBUI_PORT:-8083}"

# Проверяем существующий образ
if docker images -q "$IMAGE" &> /dev/null; then
    echo "✅ Образ $IMAGE уже существует. Используем существующий."
    BUILD_IMAGE=false
else
    echo "⚠️  Образ $IMAGE не найден. Для сборки запустите docker-run.sh или docker-compose-run.sh"
    echo "   Сейчас попробуем использовать образ из Docker Hub..."
    
    # Пробуем использовать официальный образ
    if docker pull ghcr.io/open-webui/open-webui:main; then
        IMAGE="ghcr.io/open-webui/open-webui:main"
        echo "✅ Используем официальный образ: $IMAGE"
        BUILD_IMAGE=false
    else
        echo "❌ Не удалось загрузить образ. Сборка может занять 10-15 минут."
        read -p "Продолжить сборку? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Отмена."
            exit 0
        fi
        BUILD_IMAGE=true
    fi
fi

echo "🛑 Остановка существующего контейнера..."
docker stop "$CONTAINER" 2>/dev/null || echo "Контейнер не найден или уже остановлен"
docker rm "$CONTAINER" 2>/dev/null || echo "Контейнер не найден или уже удален"

echo "💾 Проверка тома данных..."
docker volume create "$VOLUME" 2>/dev/null || echo "Том уже существует"

if [ "$BUILD_IMAGE" = true ]; then
    echo "🔨 Сборка образа (это может занять время)..."
    docker build -t "$IMAGE" .
fi

echo "🚀 Запуск контейнера..."
docker run -d \
  -p "${HOST_PORT}:8080" \
  --add-host=host.docker.internal:host-gateway \
  -v "${VOLUME}:/app/backend/data" \
  --name "$CONTAINER" \
  --restart unless-stopped \
  "$IMAGE"

echo ""
echo "✅ Open WebUI запущен!"
echo "🌐 Доступен по адресу: http://localhost:${HOST_PORT}"
echo ""
echo "📋 Команды для управления:"
echo "   docker logs $CONTAINER     - просмотр логов"
echo "   docker stop $CONTAINER     - остановить"
echo "   docker start $CONTAINER    - запустить"
echo "   docker restart $CONTAINER  - перезапустить"
echo "========================================="