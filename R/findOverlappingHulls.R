#### setup ####
#setwd("~/Desktop/Pasoh_14470_5504")

# Load libraries (install first if needed)
library(Rvcg)
library(sf)
library(terra)
library(lidR)

# set whether the segment file type is ".las" or ".ply"
fileType <- ".ply"

# ------------------------------------------------------------
# CRS: UTM Zone 19M = Zone 19 Northern Hemisphere
# EPSG:32619 (WGS84 / UTM 19N)
# If you are actually in Pasoh (Malaysia), use EPSG:32647 instead.
# ------------------------------------------------------------
lidarCRS <- "EPSG:32719"

# buffer mínimo para convertir LINESTRING -> POLYGON (metros)
# para nubes 2 cm: 0.02 (2 cm) o 0.05 (5 cm)
eps <- 0.02


#### Get segment metadata and write hull files (only run once) ####

# Get a vector of all segment file names
segmentFiles <- list.files(
  path = getwd(),
  pattern = paste0("\\", fileType, "$"),
  full.names = TRUE
)

# Make a data frame to store summary info
segmentData <- data.frame(
  file = segmentFiles,
  minX = NA_real_,
  maxX = NA_real_,
  meanX = NA_real_,
  minY = NA_real_,
  maxY = NA_real_,
  meanY = NA_real_,
  totalHt = NA_real_,
  segmentUsed = NA,
  treeID = NA,
  Notes = NA,
  stringsAsFactors = FALSE
)

# Don't include "other" cloud (-1)
segmentData <- segmentData[!grepl(pattern = "-1\\.ply$", x = segmentData$file), , drop = FALSE]

# pre-allocate list for hulls
hulls_list <- vector("list", nrow(segmentData))

for (i in 1:nrow(segmentData)) {
  
  # ---- Read cloud and stats ----
  if (fileType == ".ply") {
    pointcloud <- vcgPlyRead(segmentData$file[i], updateNormals = FALSE)
    
    x <- pointcloud$vb[1, ]
    y <- pointcloud$vb[2, ]
    z <- pointcloud$vb[3, ]
    
    segmentData$minX[i] <- min(x); segmentData$maxX[i] <- max(x); segmentData$meanX[i] <- mean(x)
    segmentData$minY[i] <- min(y); segmentData$maxY[i] <- max(y); segmentData$meanY[i] <- mean(y)
    segmentData$totalHt[i] <- max(z) - min(z)
  }
  
  if (fileType == ".las") {
    pointcloud <- readLAS(segmentData$file[i])
    
    x <- pointcloud@data$X
    y <- pointcloud@data$Y
    z <- pointcloud@data$Z
    
    segmentData$minX[i] <- min(x); segmentData$maxX[i] <- max(x); segmentData$meanX[i] <- mean(x)
    segmentData$minY[i] <- min(y); segmentData$maxY[i] <- max(y); segmentData$meanY[i] <- mean(y)
    segmentData$totalHt[i] <- max(z) - min(z)
  }
  
  # ---- Convert points to sf + CRS ----
  segmentSf <- sf::st_as_sf(
    data.frame(x = x, y = y),
    coords = c("x", "y"),
    crs = lidarCRS
  )
  
  # multipoint geometry
  segmentGeom <- sf::st_union(segmentSf)
  
  # ---- Concave hull ----
  segment_hull <- sf::st_concave_hull(segmentGeom, allow_holes = FALSE, ratio = 0.2)
  
  # ensure CRS (some ops can drop it)
  sf::st_crs(segment_hull) <- sf::st_crs(segmentSf)
  
  # ---- Make sure hull becomes polygon for SHP ----
  gt <- as.character(sf::st_geometry_type(segment_hull))
  
  # If hull degenerates to LINESTRING, buffer a tiny amount to get area
  if (gt %in% c("LINESTRING", "MULTILINESTRING")) {
    segment_hull <- sf::st_buffer(segment_hull, dist = eps)
    segment_hull <- sf::st_make_valid(segment_hull)
  }
  
  # Cast to MULTIPOLYGON (safe for shapefile polygon layers)
  segment_hull <- sf::st_cast(segment_hull, "MULTIPOLYGON", warn = FALSE)
  
  # ---- Build one-row sf feature (IMPORTANT: no st_sfc(segment_hull) nesting) ----
  hull_sf <- sf::st_sf(
    file = segmentData$file[i],
    geometry = sf::st_geometry(segment_hull)
  )
  
  hulls_list[[i]] <- hull_sf
  
  if (i %% 100 == 0) message("Procesados: ", i, "/", nrow(segmentData))
}

# Combine all hulls
allHulls <- do.call(rbind, hulls_list)

# Write metadata
write.csv(segmentData, "segmentData.csv", row.names = FALSE)

# allHulls already has CRS, but re-assert just in case
sf::st_crs(allHulls) <- lidarCRS

# ---- Write outputs ----
# 1) GeoPackage (robust, recommended)
sf::st_write(allHulls, "segmentHulls.gpkg", layer = "segmentHulls", delete_layer = TRUE)

# 2) Shapefile (now safe because all geometries are MULTIPOLYGON)
sf::st_write(allHulls, "segmentHulls.shp", delete_dsn = TRUE)


#### Define a function to find overlapping segments based on the hull ####
findSegmentsHull <- function(segmentFile, segmentHulls, bufferDist){
  
  otherHulls <- segmentHulls[segmentHulls$file != segmentFile, ]
  target     <- segmentHulls[segmentHulls$file == segmentFile, ]
  
  # buffer around target hull
  targetBuffer <- sf::st_buffer(target, dist = bufferDist)
  
  # intersects
  intersectList <- sf::st_intersects(otherHulls, targetBuffer)
  
  # keep those that intersect
  intersectHulls <- otherHulls[lengths(intersectList) > 0, ]
  
  return(intersectHulls)
}


#### Define a function to copy overlapping segments to a new folder ####
copyOverlappingSegments <- function(segmentFile, overlapNames, newDirName, moveOrCopy = c("copy","move")){
  
  moveOrCopy <- match.arg(moveOrCopy)
  
  # create new folder name if needed
  if(!dir.exists(newDirName)){
    dir.create(newDirName, recursive = TRUE)
  }
  
  # include focal segment
  overlapNames <- c(segmentFile, overlapNames)
  
  # don't move/copy -1 file ("other" cloud)
  overlapNames <- overlapNames[grep("segmented_-1\\.ply$", overlapNames, invert = TRUE)]
  
  # copy/move (IMPORTANT: 'to' must include filename)
  for (f in overlapNames) {
    dest <- file.path(newDirName, basename(f))
    ok <- file.copy(from = f, to = dest, overwrite = TRUE)
    
    if (!ok) warning("No se pudo copiar: ", f)
    
    if (moveOrCopy == "move" && ok) {
      file.remove(f)
    }
  }
}


#### Apply functions ####

# Read in information about lidar segments
# Prefer reading from GPKG (more robust than SHP)
segmentHulls <- sf::st_read("segmentHulls.gpkg", layer = "segmentHulls", quiet = TRUE)

segmentData <- read.csv("segmentData.csv", stringsAsFactors = FALSE)

# make folders for clean trees and focal segments
newDirName <- "focalTreeSegments"
cleanTreesDir <- "cleanTrees"
if(!dir.exists(cleanTreesDir)){ dir.create(cleanTreesDir) }

# choose buffer distance (in m) for identifying overlapping hulls
bufferDist <- 0

# Example focal segment
segmentFile <- file.path(getwd(), "AMA_B04_2cm_5987_159648_segmented_60.ply")

overlapHull <- findSegmentsHull(segmentFile, segmentHulls, bufferDist)

# only use segments that remain (have not been incorporated into a clean tree already)
overlapNames <- overlapHull$file
remainingNames <- list.files(path = getwd(), pattern = paste0("\\", fileType, "$"), full.names = TRUE)
overlapNames <- overlapNames[overlapNames %in% remainingNames]

moveOrCopy <- "copy" # choose whether to move "move" or copy "copy"
copyOverlappingSegments(segmentFile, overlapNames, newDirName, moveOrCopy)


#ply <- vcgPlyRead("AMA_B04_2cm_5987_159648_segmented_0.ply", updateNormals = FALSE)

#(maxX <- max(ply$vb[1, ]))
#(maxY <- max(ply$vb[2, ]))
#(maxZ <- max(ply$vb[3, ]))

#(minX <- min(ply$vb[1, ]))
#(minY <- min(ply$vb[2, ]))
#(minZ <- min(ply$vb[3, ]))
