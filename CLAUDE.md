# Contexto del proyecto: Demos de portafolio para Upwork


## Contexto general

### Quién soy y para qué es esto
Soy un desarrollador freelance en Chile armando mi perfil de Upwork. Mi posicionamiento es:
**"Python & AI Integration Developer | LLM Chatbots, APIs & Automation"**.

Estas demos son **proyectos de portafolio**. Su objetivo es que un cliente de Upwork (normalmente dueño de negocio o gerente, no siempre técnico) vea en 2 minutos que sé resolver un problema de negocio real con IA y backend.

### Cómo quiero trabajar contigo
- **Quiero entender todo lo que construimos.** Antes de cada paso importante, explícame brevemente qué vas a hacer y por qué. Cuando tomes una decisión de arquitectura, dime la alternativa que descartaste. En entrevistas me van a preguntar por este código.
- Avanza en pasos pequeños y verificables. Después de cada paso, dime cómo probarlo.
- Si algo es ambiguo, pregúntame antes de asumir.
- Conversa conmigo en **español**. Todo lo que ve el cliente (código, comentarios, README, interfaz, commits) va en **inglés**.

### Stack por defecto
- Python 3.12+, **FastAPI**, Pydantic
- PostgreSQL (Supabase o Neon en plan gratis) cuando se necesite base de datos
- LLM: API de Anthropic u OpenAI, con el proveedor configurable por variable de entorno
- Frontend mínimo: HTML + HTMX o una página simple; nada de frameworks pesados salvo que lo pida
- Docker para correr local y desplegar
- Tests con pytest para la lógica central
- Despliegue en plan gratis: Render, Railway o Fly.io

### Estándares de calidad (esto es lo que me diferencia)
- Código limpio, tipado, con nombres claros y funciones cortas.
- Configuración por variables de entorno, con un `.env.example`. **Nunca** credenciales en el repo.
- Manejo de errores visible y amigable: si la API del LLM falla, la demo lo dice claramente, no se rompe.
- Logs básicos.
- README profesional (plantilla abajo).
- Commits pequeños y descriptivos en inglés.

### Reglas para demos públicas
- **Límite de uso:** la demo desplegada debe tener rate limiting (por IP) y un tope de tokens por request, para que nadie me genere una cuenta enorme en la API. Usa el modelo más barato que funcione bien.
- **Datos ficticios y claramente marcados.** Las empresas de ejemplo son inventadas y la interfaz debe decir "Demo project with sample data". No usar nombres ni marcas de empresas reales.
- Botón o texto de "Reset demo" cuando la demo guarde datos.

### Plantilla de README
1. **Título + una línea** de qué problema resuelve (en lenguaje de negocio).
2. **Live demo** (link) + GIF o captura.
3. **The problem** — 2 o 3 líneas.
4. **The solution** — cómo funciona, con un diagrama simple (Mermaid).
5. **Tech stack**.
6. **Key decisions** — 3 a 5 bullets explicando decisiones técnicas y por qué.
7. **Run locally** — pasos exactos.
8. **What I'd add for production** — muestra criterio (auth, monitoreo, escalado, costos).
9. Nota: "Demo project built for portfolio purposes."

---

## Especificación de la demo

### Demo 2 — AI Email & Form Automation
**Escenario:** una agencia inmobiliaria ficticia recibe decenas de correos al día (consultas, visitas, reclamos, spam) y pierde tiempo clasificándolos a mano.

**Funcionalidades:**
- Entrada: correos de ejemplo (JSON/EML) y un formulario web para enviar uno nuevo. La integración real con Gmail queda como módulo opcional y documentado.
- Un LLM clasifica cada correo (categoría + urgencia) y extrae datos estructurados (nombre, teléfono, propiedad, fecha pedida) usando **salida estructurada validada con Pydantic**.
- Resultado guardado en Google Sheets (o en Postgres con vista de tabla si Sheets complica la demo pública).
- Resumen diario generado por el LLM.
- Vista web que muestra el flujo: correo entrante → clasificación → datos extraídos → destino.

**Criterios de aceptación:**
- 20 correos de ejemplo variados; clasificación correcta en al menos 18.
- Si el LLM devuelve algo inválido, se reintenta y, si vuelve a fallar, se marca para revisión humana.
- Métrica visible: "tiempo manual estimado ahorrado".

## Al terminar cada demo
1. Revisemos juntos el código: explícame las 3 partes más importantes como si me estuvieran entrevistando.
2. Genera la ficha para el portafolio de Upwork en inglés: título, descripción de 2 o 3 líneas orientada a negocio, stack y links.
3. Sugiere 3 preguntas técnicas que un cliente podría hacerme sobre este proyecto, con la respuesta.

---

## Decisiones tomadas en esta demo
- **Empresa ficticia:** Oakridge Homes (inmobiliaria, venta y arriendo).
- **Destino:** Postgres (base `email_automation` en el mismo proyecto Neon de la Demo 1) + tabla web + exportar CSV. Google Sheets queda documentado como módulo opcional.
- **LLM:** Claude Haiku 4.5 con salida estructurada (Pydantic); reintento con el error de validación; si falla de nuevo → `needs_review`.
- **Frontend:** HTMX + Jinja2 (panel server-rendered; en la Demo 1 se usó JS simple sobre una API JSON).
- **Reutilizado de la Demo 1:** config con pydantic-settings, rate limiting por IP + cuota diaria, deploy con Blueprint en Render, CI.
- **Dev local:** el proyecto está en OneDrive; correr uvicorn sin `--reload`.
- **Resumen diario:** conteos calculados en código; el LLM solo escribe titular y prioridades. Resume la bandeja actual (en la demo = "el día").
- **Urgencia "cliente amenaza con irse":** definida como media en el prompt tras variar entre corridas; eval 20/20 estable en 2 corridas (2026-10-01).
- **Tests de BD:** base separada `email_automation_test` (local, Neon) y Postgres de servicio en GitHub Actions.
