export interface FaqItem {
  q: string;
  a: string;
  /** Optional in-app link shown under the answer. */
  link?: { to: string; label: string };
}

export interface FaqCategory {
  id: string;
  title: string;
  items: FaqItem[];
}

export const FAQ: FaqCategory[] = [
  {
    id: "informes",
    title: "Informes",
    items: [
      {
        q: "¿Cómo genero un reporte?",
        a: "Ve a «Generar informe», elige la empresa y el período (puedes usar los atajos «Mes anterior», «Mes actual» o «Últimos 7 días»), el tipo de informe y el formato, y pulsa «Generar informe». Verás el avance paso a paso; al terminar aparece la tarjeta de descarga. También puedes pedirlo en lenguaje natural en el Asistente.",
        link: { to: "/informes/nuevo", label: "Generar un informe" },
      },
      {
        q: "¿Dónde encuentro los reportes generados?",
        a: "En «Informes» está el historial con la última versión de cada informe, tanto los del formulario como los del Asistente. Desde ahí puedes descargarlos o abrir su conversación para ajustarlos. Los cinco más recientes también aparecen en Inicio.",
        link: { to: "/informes", label: "Ver informes" },
      },
      {
        q: "¿Qué diferencia hay entre el formulario y el Asistente?",
        a: "El formulario usa parámetros exactos y siempre sigue los mismos pasos: el resultado es reproducible. El Asistente entiende peticiones en lenguaje natural, hace preguntas cuando falta información y permite ajustar un informe ya generado («hazlo más ejecutivo», «compáralo con el mes anterior»). Por dentro usan la misma lógica de análisis y generación.",
      },
      {
        q: "¿Puedo obtener el informe en PDF?",
        a: "Sí. En el formulario elige «PDF (.pdf)» como formato. Puedes dejar PDF como formato por defecto en Configuración > Preferencias de informes.",
        link: { to: "/configuracion", label: "Abrir Configuración" },
      },
      {
        q: "¿Por qué el informe dice que una sección «no está disponible»?",
        a: "Algunas secciones dependen de datos que la fuente no entrega (por ejemplo, el ranking de rareza de correos). En lugar de inventar cifras, el informe lo declara explícitamente.",
      },
    ],
  },
  {
    id: "fuente",
    title: "Fuente de datos",
    items: [
      {
        q: "¿Cómo configuro una fuente de datos?",
        a: "Un administrador entra a «Fuente de datos» y completa: protocolo (http/https), IP o host del servidor, ruta base, las rutas de Alertas y de Notificaciones, y el usuario y la contraseña. Luego pulsa «Probar conexión» y, si es correcta, «Guardar». Guardar vuelve a probar la conexión antes de aplicar los cambios.",
        link: { to: "/fuente-de-datos", label: "Ir a Fuente de datos" },
      },
      {
        q: "¿Qué hago si una fuente requiere usuario y contraseña?",
        a: "Escríbelos en la sección «Autenticación» de Fuente de datos. La aplicación inicia sesión sola (incluido el formulario de login de la fuente) y mantiene la sesión. La contraseña se guarda cifrada y nunca se vuelve a mostrar: para cambiarla, escribe la nueva; si dejas el campo vacío se conserva la actual.",
      },
      {
        q: "¿Cómo cambio la IP de una fuente?",
        a: "En Fuente de datos cambia solo el campo «IP o host» (por ejemplo de 10.2.85.8 a 10.2.85.9), revisa la vista previa de las URLs y guarda. No hace falta tocar código ni reiniciar: los próximos informes usan la nueva dirección. El cambio queda en la auditoría.",
      },
      {
        q: "Me sale «Primero hay que configurar la fuente de datos». ¿Qué significa?",
        a: "Falta algún dato de conexión (dirección, usuario o contraseña). Para no enviar consultas incompletas, la aplicación no intenta generar el informe. El aviso indica qué falta y lleva directamente a Fuente de datos; si no eres administrador, pide a uno que la complete.",
      },
      {
        q: "¿Qué son «Alertas» y «Notificaciones»?",
        a: "Alertas es el export detallado de alarmas (una fila por alarma): es la base del informe. Notificaciones es el panel de indicadores de la fuente (totales, tops, distribución); se usa para conciliar que el número de alarmas coincida.",
      },
    ],
  },
  {
    id: "analisis",
    title: "Análisis y estados",
    items: [
      {
        q: "¿Cómo funciona el análisis?",
        a: "Se descargan las alarmas de la empresa y el período, se normalizan (fechas, severidad, nivel de riesgo, técnica MITRE ATT&CK) y se calculan métricas: totales, tendencias, distribución por riesgo y categoría, tiempos de respuesta. Con esos datos se redacta el informe y se valida que cada hallazgo cite alarmas reales antes de generar el documento.",
        link: { to: "/documentacion#analisis", label: "Ver la explicación completa" },
      },
      {
        q: "¿Qué significa cada estado del procesamiento?",
        a: "«Entendiendo la solicitud»: el asistente interpreta tu petición. «Consultando alarmas de seguridad»: descarga desde la fuente. «Analizando los datos»: calcula métricas. «Construyendo el informe»: redacta el contenido. «Validando la estructura»: comprueba que todo esté respaldado por datos. «Generando el documento»: arma el Word/PDF. «Esperando tu respuesta»: falta información y el asistente te preguntó. «Finalizando»: guarda la versión.",
      },
      {
        q: "¿Cuánto tarda un informe?",
        a: "Normalmente entre uno y tres minutos; depende del volumen de alarmas y de la redacción. Puedes seguir usando la aplicación mientras tanto.",
      },
    ],
  },
  {
    id: "ia",
    title: "Inteligencia artificial",
    items: [
      {
        q: "¿Cómo elijo el proveedor y el modelo de IA?",
        a: "En la barra superior (botón con el chip) o en la tarjeta «Modelo de IA» del formulario: elige Cloud, vLLM, Local o Auto y luego el modelo. La lista de modelos la entrega el propio proveedor. Tu elección queda como predeterminada y puedes cambiarla en cada informe o conversación.",
        link: { to: "/configuracion", label: "Abrir Configuración" },
      },
      {
        q: "¿Qué hace el modo Auto?",
        a: "Usa el primer proveedor disponible según el orden configurado (por ejemplo vLLM y, si falla, Cloud). Antes de empezar comprueba la disponibilidad y, si una llamada falla por tiempo de espera, conexión o error del servidor, continúa con el siguiente. Cada cambio se muestra en pantalla y queda en Observabilidad y Auditoría.",
      },
      {
        q: "Elegí un proveedor y me dice que no está disponible. ¿Por qué no cambió solo?",
        a: "Cuando eliges un proveedor concreto se respeta tu elección: si no está disponible se avisa antes de empezar, con el motivo (autenticación, tiempo de espera, modelo inexistente…). Para cambio automático usa Auto.",
      },
      {
        q: "¿Cómo configuro un servidor vLLM o un modelo local?",
        a: "Un administrador entra a Configuración > Proveedores de IA, completa la URL del servidor (con el puerto), pulsa «Probar conexión», elige el modelo descubierto y guarda. Local y vLLM son proveedores independientes aunque apunten al mismo servidor.",
        link: { to: "/configuracion/proveedores-ia", label: "Proveedores de IA" },
      },
      {
        q: "¿Cómo sé que un modelo nuevo no empeora los informes?",
        a: "En Configuración > Evaluación de IA compara candidatos con los mismos casos: exactitud de extracción, severidad, riesgos, recomendaciones, calidad del informe, consistencia, latencia, errores y tokens. Si un candidato rinde peor que la línea base se señala claramente.",
        link: { to: "/configuracion/evaluacion-ia", label: "Evaluación de IA" },
      },
      {
        q: "¿Mis datos salen de la empresa?",
        a: "Con Cloud, los datos del informe se envían al proveedor en la nube elegido. Con vLLM o Local se procesan en servidores de la propia infraestructura. Las evaluaciones de calidad usan datos sintéticos, nunca datos de clientes. Las API keys se guardan cifradas y no se registran prompts ni respuestas.",
      },
    ],
  },
  {
    id: "cuenta",
    title: "Cuenta y seguridad",
    items: [
      {
        q: "¿Por qué se cerró mi sesión?",
        a: "Las sesiones se renuevan solas mientras usas la aplicación. Si la renovación falla (por ejemplo, tras mucho tiempo inactivo o si cerraste sesión en otra pestaña), por seguridad se pide iniciar sesión de nuevo.",
      },
      {
        q: "No veo Observabilidad ni Auditoría en el menú.",
        a: "Son secciones para administradores. Si necesitas acceso, pídeselo a un administrador de la plataforma.",
      },
      {
        q: "¿Cómo cambio entre modo claro y oscuro?",
        a: "Con el botón de sol/luna en la barra superior, o en Configuración > Apariencia, donde también puedes elegir «Según el sistema». La preferencia se guarda en tu cuenta.",
        link: { to: "/configuracion", label: "Abrir Configuración" },
      },
      {
        q: "¿Qué queda registrado en la auditoría?",
        a: "Inicios y cierres de sesión, intentos fallidos, cambios en la fuente de datos (incluidos cambios de IP/URL), pruebas de conexión, solicitudes, generación y descarga de informes, mensajes al asistente y cambios de preferencias. Nunca se registran contraseñas ni tokens.",
      },
    ],
  },
];
