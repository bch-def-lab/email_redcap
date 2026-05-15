library(flextable)
library(tidyr)
library(dplyr)
library(ggplot2)
library(gt)
library(clipr)
library(officer)

setwd('/Users/joshrong/Documents/DBSMM/Analysis')
source('/Users/joshrong/Documents/DBSMM/Analysis/DBSMatchMaker-Submissions_R_2026-04-15_1635.r')

#================= Clean PKAN ==================

data[data$studyid == "828454", "gene_name"] <- "PANK2"
data[data$studyid == "828455", "gene_name"] <- "PANK2"
data[data$studyid == "828456", "gene_name"] <- "PANK2"
data[data$studyid == "828464", "gene_name"] <- "MECP2"
data[data$studyid == "828500", "gene_name"] <- "18-p deletion"
data[data$studyid == "828502", "gene_name"] <- "18-p deletion"
data[data$studyid == "21", "gene_name"] <- "PLA2G6"


#================= Clean Sites ==================
n_distinct(data$submitter_institution, na.rm = TRUE)
sites <- unique(data$submitter_institution)
sites <- sites[!sites %in% c("", "SanBorjaArriaranHospital", "Texas Children's/Baylor ", "Baylor College of Medicine | Texas Children's", "University of Cologne", "UT Southwestern ", "Italian Hospital Buenos Aires", "University of sydney", "Hopital Fondation Ophtalmologique Adolphe de Rotschild")]


# ================= Clean Genes =================
n_distinct(data$gene_name, na.rm = TRUE)
genes <- unique(data$gene_name)
genes <- genes[!genes %in% c("", "still waiting results", "", "Tourette's ", "18-p Deletion Syndrome. Karyotype análisis: deletion of the short arm of chromosome 18 . 46,XX, del (18) (p11.2)", "6466", "PLA2G6 (c.2239C>T (p.Arg747Trp)) (HGNC:9039)", "MeCP2", "PKAN", "18-p deletion ", "22q11 duplication ")]



# ---- Function to get submitter info for a specific gene (with clipboard copy) ----
get_submitter_info <- function(gene_input, data, show_all = TRUE, copy_to_clipboard = TRUE) {
  
  # Filter data for the specified gene
  gene_data <- data %>%
    filter(gene_name == gene_input) %>%
    select(submitter_name, submitter_institution_v2.factor, submitter_email) %>%
    distinct() %>%
    rename(
      "Name" = submitter_name,
      "Institution" = submitter_institution_v2.factor,
      "Email" = submitter_email
    )
  
  # Check if gene exists
  if (nrow(gene_data) == 0) {
    message(paste0("Gene '", gene_input, "' not found in the dataset."))
    return(NULL)
  }
  
  # Copy to clipboard as formatted text if requested
  if (copy_to_clipboard && nrow(gene_data) > 0) {
    # Format as readable text
    clipboard_text <- paste0(
      "Submitter Information for ", gene_input, " (", nrow(gene_data), 
      ifelse(nrow(gene_data) == 1, " unique submitter)", " unique submitters)"),
      "\n\n"
    )
    
    for (i in 1:nrow(gene_data)) {
      clipboard_text <- paste0(
        clipboard_text,
        "Submitter ", i, ":\n",
        "Name: ", gene_data$Name[i], "\n",
        "Institution: ", gene_data$Institution[i], "\n",
        "Email: ", gene_data$Email[i], "\n\n"
      )
    }
    
    write_clip(clipboard_text)
    message("✓ Submitter information copied to clipboard")
  }
  
  # Check if there's only one unique submitter
  if (nrow(gene_data) == 1) {
    cat("\n=== Submitter Information for", gene_input, "===\n")
    cat("Name:       ", gene_data$Name, "\n")
    cat("Institution:", gene_data$Institution, "\n")
    cat("Email:      ", gene_data$Email, "\n\n")
    return(gene_data)
  } else {
    message(paste0("Found ", nrow(gene_data), " unique submitters for '", gene_input, "'."))
    
    if (show_all) {
      cat("\n=== All Submitters for", gene_input, "===\n\n")
      for (i in 1:nrow(gene_data)) {
        cat("Submitter", i, ":\n")
        cat("  Name:       ", gene_data$Name[i], "\n")
        cat("  Institution:", gene_data$Institution[i], "\n")
        cat("  Email:      ", gene_data$Email[i], "\n\n")
      }
      return(gene_data)
    } else {
      message("Set show_all = TRUE to see all submitters.")
      return(NULL)
    }
  }
}

# ---- Function to create submitter table (with clipboard copy) ----
get_submitter_table <- function(gene_input, data, copy_to_clipboard = TRUE) {
  
  # Filter data for the specified gene
  gene_data <- data %>%
    filter(gene_name == gene_input) %>%
    select(submitter_name, submitter_institution_v2.factor, submitter_email) %>%
    distinct()
  
  # Check if gene exists
  if (nrow(gene_data) == 0) {
    message(paste0("Gene '", gene_input, "' not found in the dataset."))
    return(NULL)
  }
  
  # Create renamed table for clipboard
  clipboard_data <- gene_data %>%
    rename(
      "Name" = submitter_name,
      "Institution" = submitter_institution_v2.factor,
      "Email" = submitter_email
    )
  
  # Copy to clipboard as formatted text if requested
  if (copy_to_clipboard) {
    clipboard_text <- paste0(
      "Submitter Information for ", gene_input, " (", nrow(clipboard_data), 
      ifelse(nrow(clipboard_data) == 1, " unique submitter)", " unique submitters)"),
      "\n\n"
    )
    
    for (i in 1:nrow(clipboard_data)) {
      clipboard_text <- paste0(
        clipboard_text,
        "Submitter ", i, ":\n",
        "Name: ", clipboard_data$Name[i], "\n",
        "Institution: ", clipboard_data$Institution[i], "\n",
        "Email: ", clipboard_data$Email[i], "\n\n"
      )
    }
    
    write_clip(clipboard_text)
    message("✓ Submitter information copied to clipboard")
  }
  
  # Create flextable
  ft <- clipboard_data %>%
    flextable() %>%
    add_header_lines(values = paste0("Submitter Information: ", gene_input, 
                                     " (", nrow(clipboard_data), 
                                     ifelse(nrow(clipboard_data) == 1, " unique submitter)", " unique submitters)"))) %>%
    bold(part = "header") %>%
    fontsize(i = 1, size = 14, part = "header") %>%
    color(i = 1, color = "#2C3E50", part = "header") %>%
    align(align = "left", part = "all") %>%
    padding(padding = 6, part = "all") %>%
    border_remove() %>%
    hline_top(border = fp_border(color = "#2C3E50", width = 2), part = "header") %>%
    hline_bottom(border = fp_border(color = "#2C3E50", width = 2), part = "body") %>%
    autofit() %>%
    theme_booktabs()
  
  return(ft)
}

# ---- Find genes with unique submitters ----
find_unique_submitter_genes <- function(data) {
  unique_genes <- data %>%
    group_by(gene_name) %>%
    summarise(
      n_unique_submitters = n_distinct(paste(submitter_name, submitter_institution_v2.factor, submitter_email)),
      .groups = 'drop'
    ) %>%
    filter(n_unique_submitters == 1) %>%
    arrange(gene_name)
  
  cat("\nGenes with only one unique submitter (", nrow(unique_genes), " total):\n\n")
  print(unique_genes)
  
  return(unique_genes)
}
# 
# # ========== EXAMPLE USAGE ==========
# 
# # ---- Example 1: Check ADCY5 (automatically copies to clipboard as text) ----
# get_submitter_info("ADCY5", data)
# 
# # ---- Example 2: Check without copying to clipboard ----
# get_submitter_info("ADCY5", data, copy_to_clipboard = TRUE)
# 
# # ---- Example 3: Create table for ADCY5 (automatically copies to clipboard) ----
# adcy5_table <- get_submitter_table("ADCY5", data)
# adcy5_table
# 
# # ---- Example 4: Save table to Word ----
# if (!is.null(adcy5_table)) {
#   save_as_docx(adcy5_table, path = "ADCY5_submitters.docx")
# }
# 
# # ---- Example 5: Find all genes with unique submitters ----
# unique_genes <- find_unique_submitter_genes(data)
# 
# # ---- Example 6: Loop through multiple genes ----
# genes_to_check <- c("ADCY5", "GNAO1", "SGCE")
# for (gene in genes_to_check) {
#   cat("\n========================================\n")
#   get_submitter_info(gene, data, copy_to_clipboard = FALSE)  # Turn off auto-copy in loops
# }
# 
# # ---- Example 7: Create tables for multiple genes and save ----
# genes_of_interest <- c("ADCY5", "GNAO1")
# 
# for (gene in genes_of_interest) {
#   table <- get_submitter_table(gene, data, copy_to_clipboard = FALSE)
#   if (!is.null(table)) {
#     filename <- paste0(gene, "_submitters.docx")
#     save_as_docx(table, path = filename)
#     cat("Saved:", filename, "\n")
#   }
# }
# ```