using Aspose.Email.Mapi;
using System;
using System.IO;
using System.Text;

class Program
{
    static void Main(string[] args)
    {
        if (args.Length < 3) return;

        string msgPath = args[0];
        string outputDir = args[1];
        string asposeLic = args[2];

        // 1. Setup License
        try
        {
            Aspose.Email.License license = new Aspose.Email.License();
            license.SetLicense(asposeLic); // Make sure .lic file is next to the .exe
        }
        catch (Exception ex)
        {
            Console.WriteLine("License Error: " + ex.Message);
        }

        // 2. Load Message
        MapiMessage msg = MapiMessage.Load(msgPath);
        int attCount = 0;

        foreach (MapiAttachment att in msg.Attachments)
        {
            /*Console.OutputEncoding = System.Text.Encoding.UTF8;
            Console.WriteLine($"Attachment Type: {att.ObjectData?.IsOutlookMessage}");
            Console.WriteLine($"DisplayName: {att.DisplayName}");
            Console.WriteLine($"FileName: {att.FileName}");
            Console.WriteLine($"LongFileName: {att.LongFileName}");
            Console.WriteLine($"Extension: {Path.GetExtension(att.FileName ?? "")}");*/

            // Determine filename
            string fileName = null; //new
            //if (!string.IsNullOrWhiteSpace(att.DisplayName)) fileName = att.DisplayName;
            if (string.IsNullOrEmpty(fileName)) fileName = att.LongFileName;
            if (string.IsNullOrEmpty(fileName)) fileName = att.FileName;
            if (string.IsNullOrEmpty(fileName)) fileName = $"attachment_{attCount}";

            // Handle embedded messages explicitly
            if (att.ObjectData != null && att.ObjectData.IsOutlookMessage)
            {
                if (!fileName.EndsWith(".msg", StringComparison.OrdinalIgnoreCase))
                    fileName += ".msg";
            }

            // Sanitize filename for Windows filesystem
            foreach (char c in Path.GetInvalidFileNameChars())
            {
                fileName = fileName.Replace(c, '_');
            }

            //Check the file ext
            if (!Path.HasExtension(fileName))
            {
                string ext = GetExtension(att);
                fileName = $"attachment_{attCount}{ext}";
                //Console.WriteLine($"Final Ext: {ext}");
            }

            //Console.WriteLine($"Final File Name: {fileName}");

            // Save to the specific output directory
            string fullPath = Path.Combine(outputDir, fileName);

            // Ensure unique name in temp folder to prevent overwrites
            while (File.Exists(fullPath))
            {
                fullPath = Path.Combine(outputDir, $"{Guid.NewGuid().ToString().Substring(0, 5)}_{fileName}");
            }

            att.Save(fullPath);
            attCount++;
        }
    }

    static string GetExtension(MapiAttachment att)
    {
        using (var ms = new MemoryStream())
        {
            att.Save(ms);
            byte[] b = ms.ToArray();

            if (b.Length >= 4)
            {
                // JPG
                if (b[0] == 0xFF && b[1] == 0xD8)
                    return ".jpg";

                // PDF
                if (b[0] == 0x25 &&
                    b[1] == 0x50 &&
                    b[2] == 0x44 &&
                    b[3] == 0x46)
                    return ".pdf";

                // PNG
                if (b[0] == 0x89 &&
                    b[1] == 0x50 &&
                    b[2] == 0x4E &&
                    b[3] == 0x47)
                    return ".png";

                // MSG (OLE Compound File)
                if (b[0] == 0xD0 &&
                    b[1] == 0xCF &&
                    b[2] == 0x11 &&
                    b[3] == 0xE0)
                    return ".msg";

                // GIF87a / GIF89a
                if (b.Length >= 6 &&
                    b[0] == 'G' &&
                    b[1] == 'I' &&
                    b[2] == 'F' &&
                    b[3] == '8' &&
                    (b[4] == '7' || b[4] == '9') &&
                    b[5] == 'a')
                    return ".gif";

                // TIFF (little-endian)
                if (b[0] == 0x49 &&
                    b[1] == 0x49 &&
                    b[2] == 0x2A &&
                    b[3] == 0x00)
                    return ".tif";

                // TIFF (big-endian)
                if (b[0] == 0x4D &&
                    b[1] == 0x4D &&
                    b[2] == 0x00 &&
                    b[3] == 0x2A)
                    return ".tif";

                // ZIP / DOCX / XLSX / PPTX
                if (b[0] == 0x50 &&
                    b[1] == 0x4B &&
                    (b[2] == 0x03 || b[2] == 0x05 || b[2] == 0x07) &&
                    (b[3] == 0x04 || b[3] == 0x06 || b[3] == 0x08))
                {
                    using (var zipMs = new MemoryStream(b))
                    using (var archive = new System.IO.Compression.ZipArchive(zipMs))
                    {
                        if (archive.Entries.Any(e => e.FullName.StartsWith("word/")))
                            return ".docx";

                        if (archive.Entries.Any(e => e.FullName.StartsWith("xl/")))
                            return ".xlsx";

                        if (archive.Entries.Any(e => e.FullName.StartsWith("ppt/")))
                            return ".pptx";
                    }

                    return ".zip";
                }

                // MP4
                if (b.Length >= 12 &&
                    b[4] == 'f' &&
                    b[5] == 't' &&
                    b[6] == 'y' &&
                    b[7] == 'p')
                    return ".mp4";

                // HEIC / HEIF
                if (b.Length >= 12 &&
                    b[4] == 'f' &&
                    b[5] == 't' &&
                    b[6] == 'y' &&
                    b[7] == 'p')
                {
                    string brand = Encoding.ASCII.GetString(b, 8, 4);

                    if (brand.StartsWith("hei") ||
                        brand.StartsWith("hei") ||
                        brand.StartsWith("mif1") ||
                        brand.StartsWith("msf1"))
                        return ".heic";
                }

                // RTF
                if (b.Length >= 5 &&
                    b[0] == '{' &&
                    b[1] == '\\' &&
                    b[2] == 'r' &&
                    b[3] == 't' &&
                    b[4] == 'f')
                    return ".rtf";
            }

            // TXT detection (last resort)
            if (IsPlainText(b))
                return ".txt";
        }

        return "";
    }

    static bool IsPlainText(byte[] data)
    {
        foreach (byte b in data.Take(4096))
        {
            if (b == 9 || b == 10 || b == 13)
                continue;

            if (b < 32 || b > 126)
                return false;
        }

        return true;
    }
}