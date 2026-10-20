
# Install arbor
#install.packages('arbor', repos = c('https://r-lidar.r-universe.dev', 'https://cloud.r-project.org'))

library(lidR)
library(arbor)

setwd("E:/AMACAYACU_TLS/Data_TLS/L20")

# Configuramos los parámetros por defecto en Arbor
params <- arbor_parameters_default
params$global$cut_above_ground = 0.25

# Leer nubes de puntos
file <- "AMA L25 ha_ROI_segment.laz"
las <- readTLS(file, select = "xyz")

# Reducir coordenadas
las@data[, `:=`(X = X - min(X), Y = Y - min(Y))]

las <- segment_ground(las)
dtm <- lidR::rasterize_terrain(las, 0.1, lidR::tin())

# Segmentación semantica
las <- wood_likelihood(las, params)
las <- segment_semantic(las, params)

# Extracción de instancias
see <- find_seeds(las, params)
las <- segment_instance(las, see, params)

# Limpiar sotobosque
las <- flag_small_trees(las, max_height = 2)

# Permite generar un buffer para omitir segmentaciones
#las <- flag_buffer(las, see, -10)

las <- colorize_trees(las, darken_foliage = TRUE)

writeLAS(las, "AMA_L25_arbor2.laz")

# Sample a random tree
#set.seed(167)
#id <- sample(unique(las$treeID), 1)

# Select a especefic tree
# Extract the largest ID tree
tabla <- table(las$treeID)

trees_ID <- data.frame(
  ID = names(tabla),
  Puntos = as.numeric(tabla)
)

id <- 415
tree <- lidR::filter_poi(las, treeID == id)

qsm  <- qsm(tree, params)
x <- plot_semantic(tree)
plot_qsm(qsm, add = x)

# QSM model from all point cloud
qsf <- qsf(las, params = params)
log <- qsf_log(qsf) # Summary of alert messages
plot(qsf)

# Save QSM model
qsf_write(qsf, "qsm_arbor.ply", ".ply")
