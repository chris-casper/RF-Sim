
`RF-sim` is a collection of scripts and LeafletJS to make a nice map that shows RF coverage. 

Designed for Ubuntu, Debian or Armbian. You should be able to easily port to other OS. 

**Usage**
---

```shell
sudo chmod +x gensite.sh
dos2unix gensite.sh
./gensite.sh
```


**Installation Options**
---

https://www.viewfinderpanoramas.org/Coverage%20map%20viewfinderpanoramas_org3.htm

Download your areas, unzip, put HGT files into one folder.

```shell

#	Install dependencies
sudo apt install g++ cmake libbz2-dev gdal-bin python3-gdal libspdlog-dev zlib1g-dev splat zip dos2unix bc

#	Get code
git clone https://github.com/W3AXL/Signal-Server.git
cd Signal-Server

#	Build instructions
mkdir build
cd build
cmake ../src
make
#	ignore warnings

#	For 30m high-resolution data, this will take overnight.
#for file in /Path/to/Folder/*.hgt; do
#    srtm2sdf-hd "$file"
#done

#	For 90m high-resolution data, this is faster and good enough for most scenarios. Still will take hours
#   Change folder name
for file in /Path/to/Folder/*.hgt; do
   srtm2sdf "$file"
done

# Move the sdf files to whatever folder you put as SDF_DIR

#	If you need to switch : to _ , use this 
#cd /mnt/c/scripts/signalserver/data/SRTM1 && for f in *:*; do mv "$f" "${f//:/_}"; done
```


**Configuration Options**
---

Go to CONFIGURATION section in script and adjust variables. This uses [Signal-Server](https://github.com/W3AXL/Signal-Server), which is an upgrade of SPLAT from the 90's. 

While this tool is intended for Meshtastic or Meshcore, you can use it for any frequency between 20MHz to 100GHz. Please do not use in polar regions.

Bare minimum is updating TX_LAT, TX_LONG, TX_HEIGHT, TX_FREQ, TX_POWER_WATTS and TX_ANTENNA_DBI

90m is working. 30m is still in progress. So leave RESOLUTION alone. 


**How to Contribute**
---

You can clone and submit pull requests. Or look for me on Meshtastic or Meshcore discord. Same username as here. 

**Acknowledgements**
---

Maybe JSON if he helps out, he's a GIS nerd. 

**Donations**
---

This is free, open-source software. Donate a refreshing beverage to your local mesh. 