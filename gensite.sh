#!/bin/bash

#===============================================================================
# SVM Signal-Server Coverage Map Generator
# Generates RF coverage maps and creates KML/KMZ files for Google Earth
#
#  Written by Chris Casper
#  v1	- 2026.01.26 - Initial
#  v1.1	- 2026.01.27 - Added GDAL
#  v1.2 - 2026.01.28 - 90m working, 30m borked
#  v1.3 - 2026.01.30 - Separate SDF directories for 30m and 90m
#  v1.4 - 2026.02.02 - Simplified 30m
#
#  # Make it executable. If using Windows, dos2unix is a good idea
# sudo chmod +x gensite.sh
# dos2unix gensite.sh
# ./gensite.sh
#
#===============================================================================

#-------------------------------------------------------------------------------
# SETUP - Run these first
#-------------------------------------------------------------------------------

#   90m global 3-arc second DEM files
#	https://www.viewfinderpanoramas.org/Coverage%20map%20viewfinderpanoramas_org3.htm
#   OR
#for lat in {38..43}; do for lon in {73..83}; do curl -fLO --retry 3 https://step.esa.int/auxdata/dem/SRTMGL3/N${lat}W$(printf "%03d" $lon).SRTMGL3.hgt.zip || true; done; done
#	Download your areas, unzip, put HGT files into a 90m folder.

#   30m global 1-arc second DEM files
#for lat in {38..43}; do for lon in {73..83}; do curl -fLO --retry 3 https://step.esa.int/auxdata/dem/SRTMGL1/N${lat}W$(printf "%03d" $lon).SRTMGL1.hgt.zip || true; done; done
#   replace lat and long to cover your area. Move files to a folder separate from the 90m.
#   Beyond 30m isn't worthwhile unless you really really know what you're doing. At that point, LIDAR is what you're going to be working with and likely need high speed compute cluster


#	Install dependencies
#sudo apt install g++ cmake libbz2-dev gdal-bin python3-gdal libspdlog-dev zlib1g-dev splat zip dos2unix bc

#	Get code
#git clone https://github.com/W3AXL/Signal-Server.git
#cd Signal-Server

#	Build instructions
#mkdir build
#cd build
#cmake ../src
#make
#	ignore warnings

#	For 30m high-resolution data, this will take overnight. Change folder to where you put the HGT, and SDF_DIR_30M.
#for file in Tile/*.hgt; do
#    srtm2sdf-hd "$file"
#done

#	For 90m high-resolution data, this is faster and good enough for most scenarios. Still will take hours. Change folder to where you put the HGT, and SDF_DIR_90M.
#for file in Tile/*.hgt; do
#   srtm2sdf "$file"
#done

# Move the sdf files to whatever folder you put as SDF_DIR

#	If you need to switch : to _ , use this. Something about python causes the issue?
#cd /mnt/c/scripts/signalserver/data/SRTM1 && for f in *:*; do mv "$f" "${f//:/_}"; done



#-------------------------------------------------------------------------------
# CONFIGURATION - Edit these variables for your setup
#-------------------------------------------------------------------------------

# Site Information
SITE_NAME="BERA-TowersRX"				# Used for output filenames (no spaces)
SITE_DESCRIPTION="RF Coverage Map"		# Description in KML file

# Paths
SIGNALSERVER_BIN="/mnt/c/scripts/signalserver/build/signalserver"		# Standard version for 1200 res and below
SIGNALSERVER_HD_BIN="/mnt/c/scripts/signalserver/build/signalserverHD"	# HD version for 3600 res
SDF_DIR_90M="/mnt/c/scripts/signalserver/data/90m"						# Standard .sdf files (90m SRTM3)
SDF_DIR_30M="/mnt/c/scripts/signalserver/data/30m"						# HD -hd.sdf files (30m SRTM1)
OUTPUT_DIR="/mnt/c/scripts/signalserver/sites"		 					# Where to save output files
COLOR_FILE="/mnt/c/scripts/signalserver/M4_dBm.dcf"						# Path to color palette file (.dcf/.scf), leave empty for default
#COLOR_FILE=""															# Blank color file for testing


# Transmitter Location
TX_LAT=41.203586                      # Latitude (decimal degrees, -70 to +70)
TX_LON=−76.964072                     # Longitude (decimal degrees, -180 to +180)
# I had an intrusive though, longtitude is 360 degrees because that's what ancient Babylonians used. Yes, it's arbitrarily. 
# Kinda sorta. It's easy to divide and there's around 360 days in a year.

# Transmitter Settings
TX_HEIGHT=5                           # Transmitter height above ground (meters if USE_METRIC=true)
TX_FREQ=906.875                        # Frequency in MHz (20 MHz to 100 GHz)
#TX_ERP=4                               # Effective Radiated Power in Watts
# Transmitter Power, cheating a bit. Update later? 
TX_POWER_WATTS=1                       # Transmitter output power in watts
TX_ANTENNA_DBI=6                       # Antenna gain in dBi

# Corrections and Calculations
TX_ERP=$(echo "scale=2; $TX_POWER_WATTS * e($TX_ANTENNA_DBI * l(10) / 10)" | bc -l)
TX_LON="${TX_LON//−/-}"

# Receiver Settings
RX_HEIGHT=2                            # Receiver height above ground
RX_THRESHOLD=-120                      # Receiver threshold (dBm if USE_DBM=true, dBuV/m otherwise)
RX_GAIN=""                             # Receiver gain in dBd (optional, for PPA reports)

# Coverage Area
RADIUS=100                             # Coverage radius (km if USE_METRIC=true)
RESOLUTION=3600                        # Pixels per tile: 300, 600, 1200 (90m), or 3600 (30m HD)

# Propagation Model
# 1=ITM, 2=LOS, 3=Hata, 4=ECC33, 5=SUI, 6=COST-Hata, 
# 7=FSPL, 8=ITWOM, 9=Ericsson, 10=Plane Earth, 11=Egli, 12=Soil
PROP_MODEL=1
PROP_MODE=""                           # 1=Urban, 2=Suburban, 3=Rural (optional)

# ITM Model Settings (only used with model 1 or 8)
RELIABILITY=50                         # Reliability percentage (1-99)
CONFIDENCE=50                          # Confidence percentage (1-99)

# Terrain Settings (all optional)
TERRAIN_CODE=""                        # 1=Water, 2=Marsh, 3=Farmland, 4=Mountain, 5=Desert, 6=Urban
TERRAIN_DIELECTRIC=""                  # Dielectric value (2-80)
TERRAIN_CONDUCTIVITY=""                # Conductivity (0.01-0.0001)
CLIMATE_CODE=""                        # 1=Equatorial, 2=Cont Sub, 3=Maritime Sub, 4=Desert, 5=Cont Temp, 6=Maritime Land, 7=Maritime Sea
GROUND_CLUTTER=""                      # Random ground clutter height

# Antenna Settings (all optional)
ANTENNA_PATTERN=""                     # Path to antenna pattern files (without .az/.el extension)
ANTENNA_ROTATION=""                    # Rotation 0-359 degrees
ANTENNA_DOWNTILT=""                    # Downtilt -10 to 90 degrees
ANTENNA_DOWNTILT_DIR=""                # Downtilt direction 0-359 degrees
HORIZONTAL_POL=false                   # true for horizontal polarization

# Output Options
USE_METRIC=true                        # true for metric (meters/km), false for imperial (feet/miles)
USE_DBM=true                           # true for dBm, false for dBuV/m field strength
KNIFE_EDGE_DIFFRACTION=false           # Enable knife edge diffraction (already on for ITM)
TERRAIN_BACKGROUND=false               # Show terrain greyscale background
CREATE_KMZ=true                        # Create compressed KMZ (false = just KML + PNG)
KEEP_PPM=true							# Keep the original PPM file
DEBUG=true                            # Enable verbose debug output



#-------------------------------------------------------------------------------
# END CONFIGURATION - No need to edit below this line
#-------------------------------------------------------------------------------

#-------------------------------------------------------------------------------
# START OF CODE - No need to edit below this line
#-------------------------------------------------------------------------------


# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status messages
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Determine which binary and SDF directory to use based on resolution
select_binary() {
    if [ "$RESOLUTION" -eq 3600 ]; then
        ACTIVE_BIN="$SIGNALSERVER_HD_BIN"
        ACTIVE_SDF_DIR="$SDF_DIR_30M"
        info "Using HD binary for 3600 resolution (30m SRTM1 data)"
        info "Using SDF directory: $ACTIVE_SDF_DIR"
    else
        ACTIVE_BIN="$SIGNALSERVER_BIN"
        ACTIVE_SDF_DIR="$SDF_DIR_90M"
        info "Using standard binary for $RESOLUTION resolution (90m SRTM3 data)"
        info "Using SDF directory: $ACTIVE_SDF_DIR"
    fi
}

# Check for required tools
check_dependencies() {
    info "Checking dependencies..."
    
    # Select the appropriate binary first
    select_binary
    
    if [ ! -x "$ACTIVE_BIN" ]; then
        error "Signal-Server binary not found or not executable: $ACTIVE_BIN"
    fi
    
    if ! command -v gdal_translate &> /dev/null; then
        error "GDAL 'gdal_translate' command not found. Install with: sudo apt-get install gdal-bin python3-gdal"
    fi
    
    if [ "$CREATE_KMZ" = true ] && ! command -v zip &> /dev/null; then
        error "zip command not found. Install with: sudo apt-get install zip"
    fi
    
    if ! command -v bc &> /dev/null; then
        error "bc command not found. Install with: sudo apt-get install bc"
    fi
    
    # Warn about resolution and data requirements. Honestly, I just do both but it takes a long while.
    if [ "$RESOLUTION" -eq 3600 ]; then
        info "INFO - 3600 resolution (30m) requires -hd.sdf files (converted with srtm2sdf-hd)"
    else
        info "INFO - $RESOLUTION resolution uses standard .sdf files (converted with srtm2sdf)"
    fi
}

# Calculate bounding box from center point and radius
calculate_bounds() {
    info "Calculating coverage bounds..."
    
    local lat=$TX_LAT
    local lon=$TX_LON
    local radius=$RADIUS
    
    # Convert radius to km if using imperial. AI slop here for math.
    if [ "$USE_METRIC" = false ]; then
        radius=$(echo "$radius * 1.60934" | bc -l)
    fi
    
    # Degrees per km at equator
    local km_per_deg_lat=111.32
    
    # Calculate latitude offset (simple, latitude doesn't affect this much)
    local lat_offset=$(echo "scale=6; $radius / $km_per_deg_lat" | bc -l)
    
    # Calculate longitude offset (depends on latitude)
    local lat_rad=$(echo "scale=10; $lat * 3.14159265359 / 180" | bc -l)
    local cos_lat=$(echo "scale=10; c($lat_rad)" | bc -l)
    local km_per_deg_lon=$(echo "scale=6; $km_per_deg_lat * $cos_lat" | bc -l)
    local lon_offset=$(echo "scale=6; $radius / $km_per_deg_lon" | bc -l)
    
    # Calculate bounds
    NORTH=$(echo "scale=6; $lat + $lat_offset" | bc -l)
    SOUTH=$(echo "scale=6; $lat - $lat_offset" | bc -l)
    EAST=$(echo "scale=6; $lon + $lon_offset" | bc -l)
    WEST=$(echo "scale=6; $lon - $lon_offset" | bc -l)
    
    info "Bounds: N=$NORTH, S=$SOUTH, E=$EAST, W=$WEST"
}

# Run Signal-Server
run_signalserver() {
    info "Running Signal-Server..."
    
    # Build command as an array to handle paths properly
    local -a cmd_args=()
    
    # Redid for SD vs HD. This part was not fun. Probably where bugs will be found. 
    cmd_args+=("$ACTIVE_BIN")
    cmd_args+=(-sdf "$ACTIVE_SDF_DIR")
    [ -n "$COLOR_FILE" ] && cmd_args+=(-color "$COLOR_FILE")
    cmd_args+=(-lat "$TX_LAT")
    cmd_args+=(-lon "$TX_LON")
    cmd_args+=(-txh "$TX_HEIGHT")
    cmd_args+=(-f "$TX_FREQ")
    cmd_args+=(-erp "$TX_ERP")
    cmd_args+=(-rxh "$RX_HEIGHT")
    cmd_args+=(-rt "$RX_THRESHOLD")
    [ -n "$RX_GAIN" ] && cmd_args+=(-rxg "$RX_GAIN")
    [ -n "$TERRAIN_CODE" ] && cmd_args+=(-te "$TERRAIN_CODE")
    [ -n "$TERRAIN_DIELECTRIC" ] && cmd_args+=(-terdic "$TERRAIN_DIELECTRIC")
    [ -n "$TERRAIN_CONDUCTIVITY" ] && cmd_args+=(-tercon "$TERRAIN_CONDUCTIVITY")
    [ -n "$CLIMATE_CODE" ] && cmd_args+=(-cl "$CLIMATE_CODE")
    [ -n "$GROUND_CLUTTER" ] && cmd_args+=(-gc "$GROUND_CLUTTER")
    cmd_args+=(-pm "$PROP_MODEL")
    [ -n "$PROP_MODE" ] && cmd_args+=(-pe "$PROP_MODE")
    [ -n "$RELIABILITY" ] && cmd_args+=(-rel "$RELIABILITY")
    [ -n "$CONFIDENCE" ] && cmd_args+=(-conf "$CONFIDENCE")
    [ -n "$ANTENNA_PATTERN" ] && cmd_args+=(-ant "$ANTENNA_PATTERN")
    [ -n "$ANTENNA_ROTATION" ] && cmd_args+=(-rot "$ANTENNA_ROTATION")
    [ -n "$ANTENNA_DOWNTILT" ] && cmd_args+=(-dt "$ANTENNA_DOWNTILT")
    [ -n "$ANTENNA_DOWNTILT_DIR" ] && cmd_args+=(-dtdir "$ANTENNA_DOWNTILT_DIR")
    [ "$HORIZONTAL_POL" = true ] && cmd_args+=(-hp)
    cmd_args+=(-R "$RADIUS")
    cmd_args+=(-res "$RESOLUTION")
    [ "$USE_METRIC" = true ] && cmd_args+=(-m)
    [ "$USE_DBM" = true ] && cmd_args+=(-dbm)
    [ "$KNIFE_EDGE_DIFFRACTION" = true ] && cmd_args+=(-ked)
    [ "$TERRAIN_BACKGROUND" = true ] && cmd_args+=(-t)
    [ "$DEBUG" = true ] && cmd_args+=(-dbg)
    cmd_args+=(-o "$OUTPUT_DIR/$SITE_NAME")
	
	# spaced out for easier copy/paste
    if [ "$DEBUG" = true ]; then
        echo ""
        echo "Command: ${cmd_args[*]}"
        echo ""
    fi
    
    # Execute the command directly
    "${cmd_args[@]}"
    
    if [ $? -ne 0 ]; then
        error "Signal-Server failed to execute"
    fi
    
    if [ ! -f "$OUTPUT_DIR/$SITE_NAME.ppm" ]; then
        error "Signal-Server did not produce output file: $OUTPUT_DIR/$SITE_NAME.ppm"
    fi
    
    info "Signal-Server completed successfully"
}

# Convert PPM to transparent PNG using GDAL
convert_to_png() {
    info "Converting PPM to transparent PNG using GDAL..."
    
    # Convert PPM to PNG using gdal_translate
    gdal_translate -of PNG "$OUTPUT_DIR/$SITE_NAME.ppm" "$OUTPUT_DIR/$SITE_NAME.png"
	# SPLAT! recommends OptiPNG. This seems to work, so leave alone?
	
    if [ $? -ne 0 ]; then
        error "Failed to convert PPM to PNG"
    fi
    
    # Make white pixels transparent using Python with GDAL
	# Cheat with python because I could copy/paste an example that worked
    python3 << EOF
from osgeo import gdal
import numpy as np

gdal.UseExceptions()

# Open the PNG
ds = gdal.Open("$OUTPUT_DIR/$SITE_NAME.png")
band_r = ds.GetRasterBand(1).ReadAsArray()
band_g = ds.GetRasterBand(2).ReadAsArray()
band_b = ds.GetRasterBand(3).ReadAsArray()

# Create alpha channel (255 = opaque, 0 = transparent)
# Make white (255,255,255) and black (0,0,0) transparent
alpha = np.where(
    ((band_r == 255) & (band_g == 255) & (band_b == 255)) |
    ((band_r == 0) & (band_g == 0) & (band_b == 0)),
    0, 255
).astype(np.uint8)

# Stack RGBA bands
rgba = np.dstack((band_r, band_g, band_b, alpha))

# Create output using MEM driver first, then copy to PNG
mem_driver = gdal.GetDriverByName('MEM')
mem_ds = mem_driver.Create('', ds.RasterXSize, ds.RasterYSize, 4, gdal.GDT_Byte)

mem_ds.GetRasterBand(1).WriteArray(band_r)
mem_ds.GetRasterBand(2).WriteArray(band_g)
mem_ds.GetRasterBand(3).WriteArray(band_b)
mem_ds.GetRasterBand(4).WriteArray(alpha)

# Copy to PNG
png_driver = gdal.GetDriverByName('PNG')
png_driver.CreateCopy("$OUTPUT_DIR/${SITE_NAME}_transparent.png", mem_ds)

mem_ds = None
ds = None
EOF

    if [ $? -ne 0 ]; then
        error "Failed to add transparency to PNG"
    fi
    
    # Replace original PNG with transparent version
    mv "$OUTPUT_DIR/${SITE_NAME}_transparent.png" "$OUTPUT_DIR/$SITE_NAME.png"
    
    if [ "$KEEP_PPM" = false ]; then
        rm -f "$OUTPUT_DIR/$SITE_NAME.ppm"
    fi
    
    info "PNG created: $OUTPUT_DIR/$SITE_NAME.png"
}

# Create KML file. Update - Modified the KML to webapp script. 
create_kml() {
    info "Creating KML file..."
    
    cat > "$OUTPUT_DIR/$SITE_NAME.kml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>$SITE_NAME</name>
    <description>$SITE_DESCRIPTION</description>
    
    <!-- Coverage Overlay -->
    <GroundOverlay>
      <name>$SITE_NAME Coverage</name>
      <description>
        Frequency: $TX_FREQ MHz
        ERP: $TX_ERP W
        TX Height: $TX_HEIGHT $([ "$USE_METRIC" = true ] && echo "m" || echo "ft")
        Radius: $RADIUS $([ "$USE_METRIC" = true ] && echo "km" || echo "mi")
        Threshold: $RX_THRESHOLD $([ "$USE_DBM" = true ] && echo "dBm" || echo "dBuV/m")
        Model: $PROP_MODEL
        Resolution: $RESOLUTION ppd
      </description>
      <Icon>
        <href>$SITE_NAME.png</href>
      </Icon>
      <LatLonBox>
        <north>$NORTH</north>
        <south>$SOUTH</south>
        <east>$EAST</east>
        <west>$WEST</west>
      </LatLonBox>
    </GroundOverlay>
    
    <!-- Transmitter Location Marker -->
    <Placemark>
      <name>$SITE_NAME TX</name>
      <description>
        Transmitter Location
        Lat: $TX_LAT
        Lon: $TX_LON
        Height: $TX_HEIGHT $([ "$USE_METRIC" = true ] && echo "m" || echo "ft") AGL
        Frequency: $TX_FREQ MHz
        ERP: $TX_ERP W
      </description>
      <Style>
        <IconStyle>
          <Icon>
            <href>http://maps.google.com/mapfiles/kml/shapes/target.png</href>
          </Icon>
        </IconStyle>
      </Style>
      <Point>
        <coordinates>$TX_LON,$TX_LAT,0</coordinates>
      </Point>
    </Placemark>
    
  </Document>
</kml>
EOF

    if [ $? -ne 0 ]; then
        error "Failed to create KML file"
    fi
    
    info "KML created: $OUTPUT_DIR/$SITE_NAME.kml"
}

# Create KMZ file
create_kmz() {
    if [ "$CREATE_KMZ" = true ]; then
        info "Creating KMZ file..."
        
        # Save current directory
        local current_dir=$(pwd)
        
        # Change to output directory for proper relative paths in KMZ
        cd "$OUTPUT_DIR"
        
        # Create KMZ (it's literally just a zip)
        zip -q "$SITE_NAME.kmz" "$SITE_NAME.kml" "$SITE_NAME.png"
        
        if [ $? -ne 0 ]; then
            cd "$current_dir"
            error "Failed to create KMZ file"
        fi
        
        # Return to original directory
        cd "$current_dir"
        
        info "KMZ created: $OUTPUT_DIR/$SITE_NAME.kmz"
    fi
}

# Print summary
print_summary() {
    echo ""
    echo "==============================================================================="
    echo "                           RF Coverage Map Complete"
    echo "==============================================================================="
    echo ""
    echo "  Site Name:      $SITE_NAME"
    echo "  Location:       $TX_LAT, $TX_LON"
    echo "  Frequency:      $TX_FREQ MHz"
    echo "  ERP:            $TX_ERP W"
    echo "  TX Height:      $TX_HEIGHT $([ "$USE_METRIC" = true ] && echo "m" || echo "ft")"
    echo "  Radius:         $RADIUS $([ "$USE_METRIC" = true ] && echo "km" || echo "mi")"
    echo "  Threshold:      $RX_THRESHOLD $([ "$USE_DBM" = true ] && echo "dBm" || echo "dBuV/m")"
    echo "  Model:          $PROP_MODEL"
    echo "  Resolution:     $RESOLUTION ppd $([ "$RESOLUTION" -eq 3600 ] && echo "(HD 30m)" || echo "(Standard 90m)")"
    echo ""
    echo "  Output Files:"
    echo "    PNG:          $OUTPUT_DIR/$SITE_NAME.png"
    echo "    KML:          $OUTPUT_DIR/$SITE_NAME.kml"
    [ "$CREATE_KMZ" = true ] && echo "    KMZ:          $OUTPUT_DIR/$SITE_NAME.kmz"
    [ "$KEEP_PPM" = true ] && echo "    PPM:          $OUTPUT_DIR/$SITE_NAME.ppm"
    echo ""
    echo "==============================================================================="
}

#-------------------------------------------------------------------------------
# Main execution
#-------------------------------------------------------------------------------

main() {
    echo ""
    echo "==============================================================================="
    echo "                    SVM Signal-Server RF Coverage Map Generator"
    echo "==============================================================================="
    echo ""
    
    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"
    
    # Run all steps
    check_dependencies
    calculate_bounds
    run_signalserver
    convert_to_png
    create_kml
    create_kmz
    print_summary
}

# Run main function
main