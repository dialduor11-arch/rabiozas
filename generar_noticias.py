#!/usr/bin/env python3
"""
RABIOZAS — Generador de noticias
Lee feeds RSS de medios LATAM y genera noticias.json
Uso: python3 generar_noticias.py
Luego sube noticias.json junto al HTML a Netlify/Vercel
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import re
import sys
import os

# ── Feeds RSS por categoría ──────────────────────────────────────────────────
# Agrega, quita o edita feeds aquí según tus preferencias
FEEDS = {
    "genero": [
        {"url": "https://www.elespectador.com/genero/feed/",      "medio": "El Espectador"},
        {"url": "https://www.nodal.am/category/genero/feed/",     "medio": "Nodal"},
        {"url": "https://www.las2orillas.co/feed/",               "medio": "Las2Orillas"},
    ],
    "ambiente": [
        {"url": "https://www.elespectador.com/medio-ambiente/feed/", "medio": "El Espectador"},
        {"url": "https://www.nodal.am/category/medio-ambiente/feed/","medio": "Nodal"},
        {"url": "https://www.animalpolitico.com/feed/",              "medio": "Animal Político"},
    ],
    "politica": [
        {"url": "https://www.elespectador.com/politica/feed/",    "medio": "El Espectador"},
        {"url": "https://lasillavacia.com/feed",                   "medio": "La Silla Vacía"},
        {"url": "https://www.nodal.am/category/america-latina/feed/","medio": "Nodal"},
    ],
    "ddhh": [
        {"url": "https://www.elespectador.com/judicial/feed/",    "medio": "El Espectador"},
        {"url": "https://www.nodal.am/category/ddhh/feed/",       "medio": "Nodal"},
        {"url": "https://www.las2orillas.co/feed/",               "medio": "Las2Orillas"},
    ],
    "investigacion": [
        {"url": "https://www.elespectador.com/investigacion/feed/","medio": "El Espectador"},
        {"url": "https://lasillavacia.com/feed",                   "medio": "La Silla Vacía"},
    ],
}

# ── Noticias propias de Rabiozas ─────────────────────────────────────────────
# Edita este bloque para agregar contenido propio del equipo
NOTICIAS_PROPIAS = [
    # Ejemplo — descomenta y edita para usar:
    # {
    #   "categoria": "genero",
    #   "titulo": "Título de la nota propia",
    #   "descripcion": "Resumen de la nota. Máximo 2-3 oraciones.",
    #   "cuerpo": "<p>Contenido completo en HTML...</p>",
    #   "autor": "Nombre de la periodista",
    #   "fecha": "2026-06-18T12:00:00",
    #   "imagen": "https://url-de-imagen.com/foto.jpg",
    #   "fuente": "Rabiozas",
    #   "url": "https://tfl.show/rabiozas",
    #   "propio": True
    # },
]

# ── Namespaces XML comunes en RSS ────────────────────────────────────────────
NS = {
    'media': 'http://search.yahoo.com/mrss/',
    'dc':    'http://purl.org/dc/elements/1.1/',
    'content': 'http://purl.org/rss/1.0/modules/content/',
}

def fetch_feed(url, timeout=10):
    """Descarga y parsea un feed RSS."""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Rabiozas/1.0)'
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return ET.fromstring(data)

def get_text(el, *tags):
    """Busca el primer tag que tenga texto."""
    for tag in tags:
        found = el.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ''

def get_image(item):
    """Extrae imagen del item RSS (varios formatos)."""
    # media:content
    mc = item.find('media:content', NS)
    if mc is not None and mc.get('url') and mc.get('medium','') == 'image':
        return mc.get('url')
    # media:thumbnail
    mt = item.find('media:thumbnail', NS)
    if mt is not None and mt.get('url'):
        return mt.get('url')
    # enclosure
    enc = item.find('enclosure')
    if enc is not None and 'image' in (enc.get('type') or ''):
        return enc.get('url', '')
    # img dentro de content:encoded o description
    for tag in ['content:encoded', 'description']:
        el = item.find(tag) if ':' not in tag else item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
        if el is not None and el.text:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', el.text)
            if m and m.group(1).startswith('http'):
                return m.group(1)
    return ''

def strip_html(text):
    """Quita etiquetas HTML y limpia el texto."""
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Entidades comunes
    for old, new in [('&amp;','&'),('&lt;','<'),('&gt;','>'),('&quot;','"'),('&nbsp;',' '),('&#39;',"'")]:
        text = text.replace(old, new)
    return text[:300]

def parse_date(date_str):
    """Convierte fecha RSS a ISO 8601."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    # Formatos comunes
    for fmt in [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S GMT',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).isoformat()
        except ValueError:
            continue
    return datetime.now(timezone.utc).isoformat()

def get_full_content(item):
    """Obtiene el contenido más completo disponible."""
    # content:encoded (artículo completo)
    ce = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
    if ce is not None and ce.text and len(ce.text.strip()) > 200:
        # Limpia scripts y estilos pero mantiene HTML
        content = re.sub(r'<script[\s\S]*?</script>', '', ce.text, flags=re.I)
        content = re.sub(r'<style[\s\S]*?</style>', '', content, flags=re.I)
        return content.strip()
    return ''

def process_feed(feed_url, medio, max_items=6):
    """Procesa un feed y devuelve lista de artículos."""
    articles = []
    try:
        root = fetch_feed(feed_url)
        channel = root.find('channel') or root
        items = channel.findall('item')[:max_items]
        for item in items:
            titulo = get_text(item, 'title')
            if not titulo:
                continue
            autor = (
                get_text(item, 'dc:author', 'author') or
                item.findtext('{http://purl.org/dc/elements/1.1/}creator') or
                'Redacción ' + medio
            )
            articles.append({
                'titulo':      titulo,
                'descripcion': strip_html(get_text(item, 'description')),
                'cuerpo':      get_full_content(item),
                'autor':       strip_html(autor),
                'fecha':       parse_date(get_text(item, 'pubDate')),
                'imagen':      get_image(item),
                'fuente':      medio,
                'url':         get_text(item, 'link') or '',
                'propio':      False,
            })
        print(f"  ✓ {medio}: {len(articles)} artículos")
    except Exception as e:
        print(f"  ✗ {medio} ({feed_url}): {e}")
    return articles

def generar_json():
    resultado = {
        'generado': datetime.now(timezone.utc).isoformat(),
        'version':  '1.0',
        'categorias': {}
    }

    for cat, feeds in FEEDS.items():
        print(f"\n📂 {cat.upper()}")
        articulos = []

        # Primero agregar noticias propias de esta categoría
        propias = [n for n in NOTICIAS_PROPIAS if n.get('categoria') == cat]
        for n in propias:
            articulos.append({
                'titulo':      n.get('titulo',''),
                'descripcion': n.get('descripcion',''),
                'cuerpo':      n.get('cuerpo',''),
                'autor':       n.get('autor','Rabiozas'),
                'fecha':       n.get('fecha', datetime.now(timezone.utc).isoformat()),
                'imagen':      n.get('imagen',''),
                'fuente':      'Rabiozas',
                'url':         n.get('url',''),
                'propio':      True,
            })
        if propias:
            print(f"  ★ {len(propias)} noticias propias de Rabiozas")

        # Luego feeds externos hasta completar 6
        max_externos = max(0, 6 - len(propias))
        per_feed = max(1, max_externos // len(feeds)) + 1
        for feed in feeds:
            if len(articulos) >= 6:
                break
            nuevos = process_feed(feed['url'], feed['medio'], max_items=per_feed)
            articulos.extend(nuevos)

        # Ordenar por fecha descendente y limitar a 6
        def sort_key(a):
            try: return a.get('fecha','')
            except: return ''
        articulos.sort(key=sort_key, reverse=True)
        resultado['categorias'][cat] = articulos[:6]
        print(f"  → {len(resultado['categorias'][cat])} artículos finales para '{cat}'")

    # Guardar JSON
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'noticias.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in resultado['categorias'].values())
    print(f"\n✅ Guardado en {out_path}")
    print(f"   {total} artículos en {len(resultado['categorias'])} categorías")
    print(f"   Generado: {resultado['generado']}")
    return out_path

if __name__ == '__main__':
    print("🗞️  RABIOZAS — Generador de noticias")
    print("=" * 45)
    generar_json()
