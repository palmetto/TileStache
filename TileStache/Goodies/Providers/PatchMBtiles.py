"""
  {
    "cache": { ... }.
    "layers":
    {
      "roads":
      {
        "provider":
        {
          class": "TileStache.Goodies.Providers.PatchMBTiles:Provider",
          "kwargs": { "tileset": "/data/mbtiles" }
        }
      }
    }
  }

MBTiles provider parameters:

  tileset:
    Required local file path to MBTiles tileset file, a SQLite 3 database file.
"""
from TileStache.py3_compat import urlparse, urljoin
from os.path import exists

# Heroku is missing standard python's sqlite3 package, so this will ImportError.
from sqlite3 import connect as _connect

from ModestMaps.Core import Coordinate

def create_tileset(filename, name, type, version, description, format, bounds=None):
    """ Create a tileset 1.1 with the given filename and metadata.

        From the specification:

        The metadata table is used as a key/value store for settings.
        Five keys are required:

          name:
            The plain-english name of the tileset.

          type:
            overlay or baselayer

          version:
            The version of the tileset, as a plain number.

          description:
            A description of the layer as plain text.

          format:
            The image file format of the tile data: png or jpg or json

        One row in metadata is suggested and, if provided, may enhance performance:

          bounds:
            The maximum extent of the rendered map area. Bounds must define
            an area covered by all zoom levels. The bounds are represented in
            WGS:84 - latitude and longitude values, in the OpenLayers Bounds
            format - left, bottom, right, top. Example of the full earth:
            -180.0,-85,180,85.
    """

    if format not in ('png', 'jpg', 'json', 'pbf'):
        raise Exception('Format must be one of "png", "jpg", "json" or "pbf", not "%s"' % format)

    db = _connect(filename)

    db.execute('CREATE TABLE metadata (name TEXT, value TEXT, PRIMARY KEY (name))')
    db.execute('CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)')
    db.execute('CREATE UNIQUE INDEX coord ON tiles (zoom_level, tile_column, tile_row)')

    db.execute('INSERT INTO metadata VALUES (?, ?)', ('name', name))
    db.execute('INSERT INTO metadata VALUES (?, ?)', ('type', type))
    db.execute('INSERT INTO metadata VALUES (?, ?)', ('version', version))
    db.execute('INSERT INTO metadata VALUES (?, ?)', ('description', description))
    db.execute('INSERT INTO metadata VALUES (?, ?)', ('format', format))

    if bounds is not None:
        db.execute('INSERT INTO metadata VALUES (?, ?)', ('bounds', bounds))

    db.commit()
    db.close()

def tileset_exists(filename):
    """ Return true if the tileset exists and appears to have the right tables.
    """
    if not exists(filename):
        return False

    # this always works
    db = _connect(filename)
    db.text_factory = bytes

    try:
        db.execute('SELECT name, value FROM metadata LIMIT 1')
        db.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles LIMIT 1')
    except:
        return False

    return True

def tileset_info(filename):
    """ Return name, type, version, description, format, and bounds for a tileset.

        Returns None if tileset does not exist.
    """
    if not tileset_exists(filename):
        return None

    db = _connect(filename)
    db.text_factory = bytes

    info = []

    for key in ('name', 'type', 'version', 'description', 'format', 'bounds'):
        value = db.execute('SELECT value FROM metadata WHERE name = ?', (key, )).fetchone()
        info.append(value and value[0] or None)

    return info

def list_tiles(filename):
    """ Get a list of tile coordinates.
    """
    db = _connect(filename)
    db.text_factory = bytes

    tiles = db.execute('SELECT tile_row, tile_column, zoom_level FROM tiles')
    tiles = (((2**z - 1) - y, x, z) for (y, x, z) in tiles) # Hello, Paul Ramsey.
    tiles = [Coordinate(row, column, zoom) for (row, column, zoom) in tiles]

    return tiles

def get_tile(filename, coord):
    """ Retrieve the mime-type and raw content of a tile by coordinate.

        If the tile does not exist, None is returned for the content.
    """
    db = _connect(filename)
    db.text_factory = bytes

    formats = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'json': 'application/json',
        'pbf': 'application/x-protobuf',
        None: None
    }

    format = db.execute("SELECT value FROM metadata WHERE name='format'").fetchone()
    format = format and format[0] or None
    mime_type = formats[format]

    tile_row = (2**coord.zoom - 1) - coord.row # Hello, Paul Ramsey.
    q = 'SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?'
    content = db.execute(q, (coord.zoom, coord.column, tile_row)).fetchone()
    content = content and content[0] or None

    return mime_type, content

def delete_tile(filename, coord):
    """ Delete a tile by coordinate.
    """
    db = _connect(filename)
    db.text_factory = bytes

    tile_row = (2**coord.zoom - 1) - coord.row # Hello, Paul Ramsey.
    q = 'DELETE FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?'
    db.execute(q, (coord.zoom, coord.column, tile_row))

def put_tile(filename, coord, content):
    """
    """
    db = _connect(filename)
    db.text_factory = bytes

    tile_row = (2**coord.zoom - 1) - coord.row # Hello, Paul Ramsey.
    q = 'REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)'
    db.execute(q, (coord.zoom, coord.column, tile_row, buffer(content)))

    db.commit()
    db.close()

class Provider:
    """ MBTiles provider.

        See module documentation for explanation of constructor arguments.
    """
    def __init__(self, layer, tileset):
        """
        """
        sethref = urljoin(layer.config.dirpath, tileset)
        scheme, h, path, q, p, f = urlparse(sethref)

        if scheme not in ('file', ''):
            raise Exception('Bad scheme in MBTiles provider, must be local file: "%s"' % scheme)

        self.tileset = path
        self.layer = layer

    @staticmethod
    def prepareKeywordArgs(config_dict):
        """ Convert configured parameters to keyword args for __init__().
        """
        return {'tileset': config_dict['tileset']}

    def renderTile(self, width, height, srs, coord):
        """ Retrieve a single tile, return a TileResponse instance.
        """
        mime_type, content = get_tile(self.tileset, coord)
        formats = {
            'image/png': 'PNG',
            'image/jpeg': 'JPG',
            None: None
        }
        return TileResponse(formats[mime_type], content)

    def getTypeByExtension(self, extension):
        """ Get MIME-type and format by file extension.

            This only accepts "png", "jpg", "json" or "pbf".
        """
        if extension.lower() == 'json':
            return 'application/json', 'JSON'

        elif extension.lower() == 'png':
            return 'image/png', 'PNG'

        elif extension.lower() == 'jpg':
            return 'image/jpg', 'JPEG'

        elif extension.lower() == 'pbf':
            return 'application/x-protobuf', 'PBF'

        else:
            raise KnownUnknown('MBTiles only makes .png, .jpg, .json and .pbf tiles, not "%s"' % extension)

class TileResponse:
    """ Wrapper class for tile response that makes it behave like a PIL.Image object.

        TileStache.getTile() expects to be able to save one of these to a buffer.

        Constructor arguments:
        - format: 'PNG' or 'JPEG'.
        - content: Raw response bytes.
    """
    def __init__(self, format, content):
        self.format = format
        self.content = content

    def save(self, out, format):
        if self.format is not None and format.lower() != self.format.lower():
            raise Exception('Requested format "%s" does not match tileset format "%s"' % (format, self.format))
        out.write(self.content)

class Cache:
    """ Cache provider for writing to MBTiles files.

        This class is not exposed as a normal cache provider for TileStache,
        because MBTiles has restrictions on file formats that aren't quite
        compatible with some of the looser assumptions made by TileStache.
        Instead, this cache provider is provided for use with the script
        tilestache-seed.py, which can be called with --to-mbtiles option
        to write cached tiles to a new tileset.
    """
    def __init__(self, filename, format, name):
        """
        """
        self.filename = filename

        if not tileset_exists(filename):
            create_tileset(filename, name, 'baselayer', '0', '', format.lower())

    def lock(self, layer, coord, format):
        return

    def unlock(self, layer, coord, format):
        return

    def remove(self, layer, coord, format):
        """ Remove a cached tile.
        """
        delete_tile(self.filename, coord)

    def read(self, layer, coord, format):
        """ Return raw tile content from tileset.
        """
        return get_tile(self.filename, coord)[1]

    def save(self, body, layer, coord, format):
        """ Write raw tile content to tileset.
        """
        put_tile(self.filename, coord, body)