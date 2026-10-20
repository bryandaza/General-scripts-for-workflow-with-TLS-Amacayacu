#Camb_nomb_ply
# ============================================
# COPIAR Y RENOMBRAR ARCHIVOS PLY
# ============================================

setwd("E:/AMACAYACU_TLS/Data_TLS/Palmas")

datos1 <- read.csv("match_stemtag_palms_L20_ply.csv")
datos2 <- read.csv("match_stemtag_palms_X10_ply.csv")
datos3 <- read.csv("match_stemtag_palms_B04_ply.csv")

datos <- rbind(datos1, datos2, datos3)

datos <- subset(datos, datos$matched == "True")

# Rutas

folder_origen <- "E:/AMACAYACU_TLS/Data_TLS/Palmas/Clean_all"

folder_destino <- "E:/AMACAYACU_TLS/Data_TLS/Palmas/Clean_all"


# Recorrer las filas del CSV
for (i in seq_len(nrow(datos))) {
  
  # Obtener nombres del CSV
  nombre_actual <- datos$ply_file[i]
  nombre_nuevo  <- datos$shape_id[i]
  
  nombre_actual <- sub(".ply", "", nombre_actual)
  
  # Construir rutas de origen y destino
  ruta_origen <- file.path(
    folder_origen,
    paste0(nombre_actual, " - Cloud.ply")
  )
  
  ruta_destino <- file.path(
    folder_destino,
    paste0(nombre_nuevo, ".ply")
  )
  
  # Comprobar si el archivo existe
  if (file.exists(ruta_origen)) {
    
    # Copiar archivo con el nuevo nombre
    resultado <- file.copy(
      from = ruta_origen,
      to = ruta_destino,
      overwrite = FALSE
    )
    
    if (resultado) {
      cat("Copiado:", nombre_actual, "->", nombre_nuevo, ".ply\n")
    } else {
      cat("ERROR al copiar:", nombre_actual, "\n")
    }
    
  } else {
    
    cat("NO ENCONTRADO:", ruta_origen, "\n")
    
  }
}

cat("\nProceso finalizado.\n")

