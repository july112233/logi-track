# LOGI-TRACK

Aplicación web para registrar y analizar los tiempos de las etapas logísticas de pedidos: **Picking, Packing y Despacho**.

## Archivos del proyecto

- `app.py`: código principal de LOGI-TRACK.
- `requirements.txt`: bibliotecas que necesita el programa.
- `.streamlit/config.toml`: configuración visual de Streamlit.
- `data/`: carpeta donde se crea el historial `pedidos.json`.

## Ejecutar en un computador

1. Instalar Python 3.11 o 3.12.
2. Abrir una terminal dentro de esta carpeta.
3. Crear un entorno virtual:

   ```bash
   py -m venv .venv
   ```

4. Activarlo en Windows:

   ```bash
   .venv\Scripts\activate
   ```

5. Instalar las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

6. Iniciar LOGI-TRACK:

   ```bash
   streamlit run app.py
   ```

## Publicar en Streamlit Community Cloud

1. Crear una cuenta gratuita en GitHub.
2. Crear un repositorio llamado `logi-track`.
3. Subir al repositorio el contenido de esta carpeta, conservando la carpeta `.streamlit`.
4. Entrar en <https://share.streamlit.io/> e iniciar sesión con GitHub.
5. Seleccionar **Create app** / **Deploy an app**.
6. Elegir el repositorio `logi-track`, la rama `main` y el archivo principal `app.py`.
7. Pulsar **Deploy**. Streamlit instalará automáticamente las dependencias de `requirements.txt`.
8. Compartir el enlace web generado con la profesora.

## Importante sobre el historial

La versión actual guarda los pedidos en `data/pedidos.json`. En un despliegue gratuito en la nube, el almacenamiento local del servidor no debe considerarse permanente: los registros pueden perderse si la aplicación se reinicia, se reconstruye o se vuelve a desplegar. Para conservarlos de forma duradera entre reinicios, habría que conectar una base de datos externa.

El archivo `data/pedidos.json` está excluido de Git para evitar publicar datos de prueba o registros reales.

## Uso básico

1. Abrir **Registrar pedido**.
2. Escribir un código único y el tiempo objetivo.
3. Ingresar los minutos de Picking, Packing y Despacho. Al menos una etapa debe ser mayor que cero.
4. Registrar el pedido y revisar el resultado.
5. Consultar el **Panel principal**, el **Historial**, el **Análisis logístico** y los **Reportes**.
