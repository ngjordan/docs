import SwiftUI
import UniformTypeIdentifiers

@main
struct IridiumDocsApp: App {
    @State private var showingAbout = false

    var body: some Scene {
        // DocumentGroup hands the closure a `Document` reference (a class), so
        // the binding is `$file`, not a projected value on a value type.
        DocumentGroup(newDocument: Document()) { $file in
            DocumentView(document: $file)
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            showingAbout = true
                        } label: {
                            Label("About", systemImage: "info.circle")
                        }
                    }
                }
                .sheet(isPresented: $showingAbout) {
                    AboutView()
                }
        }
    }
}

/// A document is a single block of text. `Document` is the reference type the
/// `DocumentGroup` hands us; `text` is the content.
final class Document: ObservableObject, FileDocument {
    @Published var text: String = ""

    static var readableContentTypes: [UTType] { [.plainText] }

    init() {
        text = "Iridium Docs"
    }

    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents,
              let s = String(data: data, encoding: .utf8) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        text = s
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
    }
}

struct DocumentView: View {
    @Binding var document: Document

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // The ribbon-strip: a compact toolbar row, in the Iridium green.
            HStack(spacing: 16) {
                Label("Iridium Docs", systemImage: "doc.text")
                    .font(.headline)
                    .foregroundStyle(Color(red: 0.043, green: 0.431, blue: 0.310))
                Divider()
                Button("Bold") { }
                Button("Italic") { }
                Spacer()
                Text("\(document.text.count) characters")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(.quaternary)

            Divider()

            // The page.
            ScrollView {
                TextEditor(text: $document.text)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .padding(24)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(Color(.systemGroupedBackground))
        }
        .navigationTitle("Iridium Docs")
    }
}

struct AboutView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Iridium Docs")
                .font(.title2.bold())
            Text("A word processor by Iridium Technologies, Inc.")
                .font(.subheadline)
            Divider()
            Text("Based on WordCraft by the ArtCraft team.")
                .font(.footnote)
            Text("MIT OR Apache-2.0.")
                .font(.footnote)
            Text("Bundle: ph.iridium.docs")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Close") { }
            }
        }
        .padding(24)
        .frame(width: 360)
    }
}
