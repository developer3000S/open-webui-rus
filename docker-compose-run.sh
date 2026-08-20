#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Запуск Open WebUI через Docker Compose
# ---------------------------------------------------------------------------

echo "========================================="
echo "Open WebUI Docker Compose Runner"
echo "========================================="

# Проверяем доступность docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose не найден. Используем стандартный docker..."
    if ! command -v docker &> /dev/null; then
        echo "❌ Docker не установлен"
        exit 1
    fi
    # Запускаем через docker-compose plugin
    DOCKER_COMPOSE_CMD="docker compose"
else
    DOCKER_COMPOSE_CMD="docker-compose"
fi

# Проверяем порт
HOST_PORT="${OPEN_WEBUI_PORT:-8083}"
if command -v nc &> /dev/null; then
    if nc -z localhost "$HOST_PORT" &> /dev/null; then
        echo "⚠️  Порт $HOST_PORT уже используется. Останавливаем существующие контейнеры..."
        $DOCKER_COMPOSE_CMD down 2>/dev/null || true
    fi
fi

echo "🛑 Остановка существующих контейнеров..."
$DOCKER_COMPOSE_CMD down 2>/dev/null || echo "Контейнеры не найдены или уже остановлены"

echo "🔨 Сборка и запуск контейнеров..."
if ! $DOCKER_COMPOSE_CMD up -d --build; then
    echo "❌ Ошибка запуска docker-compose"
    exit 1
fi

echo "⏳ Ожидание запуска контейнера..."
sleep 5

echo "📋 Проверка состояния..."
if ! $DOCKER_COMPOSE_CMD ps; then
    echo "⚠️  Не удалось получить статус контейнеров"
fi

echo ""
echo "✅ Open WebUI запущен через Docker Compose!"
echo ""
echo "🌐 Доступен по адресу: http://localhost:${HOST_PORT}"
echo "📁 Данные сохраняются в томе: open-webui"
echo ""
echo "📋 Полезные команды:"
echo "   $DOCKER_COMPOSE_CMD logs          - просмотр логов"
echo "   $DOCKER_COMPOSE_CMD ps            - статус контейнеров"
echo "   $DOCKER_COMPOSE_CMD down          - остановить и удалить контейнеры"
echo "   $DOCKER_COMPOSE_CMD restart       - перезапустить контейнеры"
echo "   docker exec -it open-webui bash  - войти в контейнер"
echo "========================================="