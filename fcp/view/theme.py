from PyQt6.QtGui import QFont

FONT_FAMILY     = 'Helvetica'
FONT_SIZE       = 14
FONT_SIZE_LARGE = 16
FONT_SIZE_SMALL = 12

# Node / health status colors
STATUS_HEALTHY = '#388E3C'   # green
STATUS_WARNING = '#F57F17'   # dark amber — readable on light bg (#FFC107 has poor contrast)
STATUS_ERROR   = '#C62828'   # dark red
STATUS_UNKNOWN = '#757575'   # grey

# RAT indicator colors
RAT_DETECTED = '#1565C0'   # dark blue
RAT_TRACKING = '#F57F17'   # dark amber
RAT_ENGAGED      = '#C62828'   # dark red
RAT_NEUTRALIZED  = '#9E9E9E'   # grey — hit confirmed, no longer tracked

# Alert severity text colors (for system-default / light backgrounds)
ALERT_INFO    = '#212121'   # near-black
ALERT_WARNING = '#E65100'   # deep orange — #FFC107 has poor contrast on light bg
ALERT_ERROR   = '#C62828'   # dark red

# Sensor toggle button colors
SENSOR_ENABLED_BG  = 'lightgreen'
SENSOR_DISABLED_BG = 'red'

# Engage button colors
ENGAGE_BG_ACTIVE   = '#CC0000'   # red — armed
ENGAGE_FG_ACTIVE   = '#FFFFFF'
ENGAGE_BG_INACTIVE = '#D9D9D9'   # grey — no zone-3 target
ENGAGE_FG_INACTIVE = '#A0A0A0'
ENGAGE_BG_STOP     = '#E65100'   # deep orange — engagement active
ENGAGE_FG_STOP     = '#FFFFFF'

ENGAGE_PAD_X    = 20
ENGAGE_PAD_Y    = 10
ENGAGE_GRACE_MS = 2500

# Map widget — custom painter
MAP_BG            = '#F0F0F0'   # light window background
MAP_TEXT          = '#212121'   # near-black
MAP_ZONE_BORDER   = 'black'
MAP_NODE_BG       = '#FFFFFF'   # white widget background
MAP_NODE_SUBTITLE = '#616161'   # secondary text
MAP_NODE_DIVIDER  = '#E0E0E0'   # light separator
MAP_NODE_STAT     = '#424242'   # body text
MAP_NODE_INACTIVE = '#9E9E9E'   # disabled / no-data state
MAP_ZONE1_FILL    = '#A5D6A7'
MAP_ZONE2_FILL    = '#FFE082'
MAP_ZONE3_FILL    = '#EF9A9A'


def apply(app):
    """Apply application-wide font. Call once after QApplication is created."""
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE))
