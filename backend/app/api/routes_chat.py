from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_auth
from app.domain.ai_fallback import generate_local_diagnosis
from app.domain.ai_prompt import build_system_prompt
from app.integrations.groq_client import query_groq
from app.integrations.supabase_client import clear_chat_history, fetch_chat_history, insert_chat_message
from app.models.schemas import ChatHistoryResponse, ChatMessageRequest, ChatMessageResponse
from app.services.ai_context import NoActiveFeedError, build_ai_context

router = APIRouter(prefix="/chat", tags=["chat"])

# Mismo factor que /market/ai-diagnosis -- ver comentario en routes_rest.py.
NQ_QQQ_RATIO = 41.125

# Turnos previos que se le pasan a Groq como memoria de la conversación
# (12 mensajes = ~6 idas y vueltas) -- lo suficiente para continuidad
# real sin disparar el consumo de tokens en cada mensaje nuevo.
CHAT_HISTORY_TURNS = 12


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(username: str = Depends(require_auth)):
    """Historial del asistente IA, privado por usuario (columna
    user_email de chat_messages, ver supabase_client.py) -- port del
    widget de chat del sidebar de app.py (~línea 2446), reconstruido acá
    como un panel flotante persistente en vez de un st.popover."""
    messages = await fetch_chat_history(username)
    return ChatHistoryResponse(messages=messages)


@router.delete("/history")
async def delete_chat_history(username: str = Depends(require_auth)):
    """Borra SOLO el historial del usuario autenticado -- nunca el de los
    otros (bug ya corregido en app.py: antes 'Limpiar' borraba la tabla
    completa, compartida entre los 3 usuarios)."""
    await clear_chat_history(username)
    return {"ok": True}


@router.post("/message", response_model=ChatMessageResponse)
async def post_chat_message(body: ChatMessageRequest, username: str = Depends(require_auth)):
    """Pregunta libre al asistente IA (a diferencia de /market/ai-diagnosis,
    que siempre pide el mismo informe fijo) -- port de la rama
    mensaje_usuario de consultar_ia en app.py: mismo contexto de
    mercado/VIX/velas, pero el prompt final es la pregunta tal cual la
    escribió el usuario. Guarda ambos mensajes (user + assistant) en
    Supabase para que el historial sobreviva a un refresh de página."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")

    try:
        ctx = await build_ai_context(body.symbol)
    except NoActiveFeedError:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {body.symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    # Leer el historial ANTES de insertar el mensaje nuevo (si no, el
    # propio mensaje que se está por responder quedaría duplicado al
    # final del historial que se le pasa a Groq).
    history = await fetch_chat_history(username, limit=CHAT_HISTORY_TURNS)

    await insert_chat_message(username, "user", message)

    # Mismo criterio que /market/ai-diagnosis: un ratio manual mandado
    # desde la web tiene prioridad sobre la constante fija.
    conversion_ratio = body.conversion_ratio if body.conversion_ratio and body.conversion_ratio > 0 else NQ_QQQ_RATIO

    system_prompt = build_system_prompt(
        ticker=body.symbol,
        spot=ctx["spot"],
        metrics=ctx["metrics"],
        vix_val=ctx["vix_val"],
        intraday_context=ctx["intraday_context"],
        conversion_ratio=conversion_ratio,
        overnight_profile=ctx.get("overnight_profile"),
        cash_profile=ctx.get("cash_profile"),
        vix_term_structure=ctx.get("vix_term_structure"),
        ndx_cross_check=ctx.get("ndx_cross_check"),
        implied_range=ctx.get("implied_range"),
        oi_is_volume_proxy=ctx.get("oi_is_volume_proxy", False),
        macro_levels=ctx.get("macro_levels"),
        vix_gamma_levels=ctx.get("vix_gamma_levels"),
        economic_calendar=ctx.get("economic_calendar"),
    )

    ai_text = await query_groq(system_prompt, message, history=history)
    source = "groq"
    if not ai_text:
        ai_text = generate_local_diagnosis(body.symbol, ctx["spot"], ctx["metrics"], ctx["vix_val"], conversion_ratio)
        source = "local"

    await insert_chat_message(username, "assistant", ai_text)

    return ChatMessageResponse(content=ai_text, source=source)
