//! Format crates registered with the I/O dispatcher.

use iridium_docs_doc::Document;

/// Open a format other than plain text / JSON; files that give no page size (Markdown, HTML)
/// start on `page`.
pub fn open(ext: &str, bytes: &[u8], page: &iridium_docs_doc::SectionProps) -> Option<Result<Document, String>> {
    match ext {
        "docx" | "docm" | "dotx" | "dotm" => Some(crate::io::read_docx(bytes, None).map_err(|e| e.to_string())),
        "doc" | "dot" => Some(iridium_docs_docbin::read(bytes).map_err(|e| e.to_string())),
        // Word XML Document (Flat OPC) or Word 2003 XML, told apart by the root element.
        "xml" => Some(iridium_docs_docx::read_xml(bytes).map_err(|e| e.to_string())),
        // HTML, Markdown, ODT, RTF…: pictures fit the text width (see `io::fit_pictures`).
        other => iridium_docs_formats::import_on(other, bytes, page).map(|r| {
            r.map(|mut doc| {
                crate::io::fit_pictures(&mut doc);
                doc
            })
        }),
    }
}

/// Save to a format other than plain text / JSON.
pub fn save(ext: &str, doc: &Document, opts: &crate::io::ExportOptions) -> Option<Result<Vec<u8>, String>> {
    // .docx/.docm/.dotx/.dotm: the extension picks the package flavour Word expects.
    if let Some(flavor) = iridium_docs_docx::Flavor::from_ext(ext) {
        return Some(iridium_docs_docx::write_as(doc, flavor).map_err(|e| e.to_string()));
    }
    match ext {
        "xml" if opts.word2003 => Some(iridium_docs_docx::write_wordml2003(doc).map_err(|e| e.to_string())),
        "xml" => Some(iridium_docs_docx::write_flat(doc).map_err(|e| e.to_string())),
        "png" => Some(render_png(doc, 0, 2.0, opts)),
        "pdf" => {
            let pdf = iridium_docs_pdf::PdfOptions {
                include_markup: opts.markup,
                comments: opts.markup && opts.comments,
                numeral: opts.numeral,
                ..Default::default()
            };
            Some(iridium_docs_pdf::export(doc, &pdf).map_err(|e| e.to_string()))
        }
        other => iridium_docs_formats::export_with(other, doc, &iridium_docs_formats::ExportOptions { comments: opts.markup && opts.comments }),
    }
}

/// Render page `page` as PNG at `scale` px/pt. With Print Markup's comments the page has its
/// markup area with the comments in balloons (page images always show tracked changes).
pub fn render_png(doc: &Document, page: usize, scale: f32, opts: &crate::io::ExportOptions) -> Result<Vec<u8>, String> {
    let lo = iridium_docs_layout::LayoutOptions { comment_balloons: opts.markup && opts.comments, numeral: opts.numeral, ..Default::default() };
    let l = iridium_docs_layout::layout(doc, &mut iridium_docs_layout::LayoutCache::new(), &lo);
    let p = l.pages.get(page).ok_or_else(|| format!("no page {}", page + 1))?;
    let img = iridium_docs_render::render_page(doc, p, scale, &Default::default());
    Ok(img.to_png())
}
