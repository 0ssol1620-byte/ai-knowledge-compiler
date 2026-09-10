param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Render", "Provenance")]
    [string]$Action,

    [ValidateSet("docx", "pptx", "xlsx")]
    [string]$Kind,

    [string]$InputPath,

    [string]$OutputPdf,

    [ValidateSet("p", "tbl")]
    [string]$TargetKind,

    [int]$TargetOrdinal,

    [string]$ProcessReceiptPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $hasher.ComputeHash($stream)
        return "sha256:" + ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
        $stream.Dispose()
    }
}

function Get-OfficeExecutable([string]$FileName) {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Microsoft Office\root\Office16\$FileName"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft Office\root\Office16\$FileName")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "OFFICE16_EXECUTABLE_MISSING"
}

function Get-OfficeProvenance {
    $definitions = @(
        @{ Name = "word"; FileName = "WINWORD.EXE" },
        @{ Name = "powerpoint"; FileName = "POWERPNT.EXE" },
        @{ Name = "excel"; FileName = "EXCEL.EXE" }
    )
    $applications = foreach ($definition in $definitions) {
        $path = Get-OfficeExecutable $definition.FileName
        $version = (Get-Item -LiteralPath $path).VersionInfo
        [ordered]@{
            name = $definition.Name
            file_version = $version.FileVersion
            product_version = $version.ProductVersion
            executable_path = $path
            executable_size_bytes = (Get-Item -LiteralPath $path).Length
            executable_sha256 = Get-Sha256 $path
        }
    }
    [ordered]@{
        schema = "tavonel.office16_provenance.v1"
        applications = @($applications)
    }
}

function Release-ComObject($Value) {
    if ($null -ne $Value -and [System.Runtime.InteropServices.Marshal]::IsComObject($Value)) {
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($Value)
    }
}

function Write-OfficeProcessReceipt(
    [int[]]$BeforeProcessIds,
    [datetime]$CreationStartedUtc,
    [string]$ExpectedProcessName,
    [string]$ReceiptPath
) {
    if (-not $ReceiptPath) { throw "OFFICE_PROCESS_RECEIPT_REQUIRED" }
    $receiptParent = (Resolve-Path -LiteralPath (Split-Path -Parent $ReceiptPath)).Path
    $resolvedReceipt = Join-Path $receiptParent (Split-Path -Leaf $ReceiptPath)
    if (Test-Path -LiteralPath $resolvedReceipt) { throw "OFFICE_PROCESS_RECEIPT_EXISTS" }
    $candidates = @(
        Get-Process -Name $ExpectedProcessName -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Id -notin $BeforeProcessIds -and
                $_.StartTime.ToUniversalTime() -ge $CreationStartedUtc.AddSeconds(-2)
            }
    )
    if ($candidates.Count -ne 1) { throw "OFFICE_PROCESS_ID_AMBIGUOUS" }
    $process = $candidates[0]
    $receiptJson = [ordered]@{
        schema = "tavonel.office_process_receipt.v1"
        process_id = [int]$process.Id
        process_name = $process.ProcessName
        process_started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
        before_process_ids = @($BeforeProcessIds)
        creation_started_at_utc = $CreationStartedUtc.ToUniversalTime().ToString("o")
        stage = "application_created"
    } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText(
        $resolvedReceipt,
        $receiptJson,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Set-OfficeProcessStage([string]$ReceiptPath, [string]$Stage) {
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
    $receipt.stage = $Stage
    $receiptJson = $receipt | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText(
        $ReceiptPath,
        $receiptJson,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

if ($Action -eq "Provenance") {
    Get-OfficeProvenance | ConvertTo-Json -Depth 5 -Compress
    exit 0
}

if (-not $Kind -or -not $InputPath -or -not $OutputPdf) {
    throw "RENDER_ARGUMENTS_REQUIRED"
}

[string]$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
[string]$resolvedOutputParent = (
    Resolve-Path -LiteralPath (Split-Path -Parent $OutputPdf)
).Path
[string]$resolvedOutput = Join-Path $resolvedOutputParent (Split-Path -Leaf $OutputPdf)
if (Test-Path -LiteralPath $resolvedOutput) {
    throw "OUTPUT_MUST_NOT_EXIST"
}

$application = $null
$document = $null
$renderDocument = $null
$renderRange = $null
$worksheet = $null
$targetRange = $null
$resolvedPageNumber = 1
$locatorProof = "first_exported_page"
try {
    if ($Kind -eq "docx") {
        [int[]]$beforeProcessIds = @(Get-Process -Name "WINWORD" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
        $creationStartedUtc = (Get-Date).ToUniversalTime()
        $application = New-Object -ComObject Word.Application
        $application.Visible = $false
        $application.DisplayAlerts = 0
        $application.AutomationSecurity = 3
        Write-OfficeProcessReceipt $beforeProcessIds $creationStartedUtc "WINWORD" $ProcessReceiptPath
        Set-OfficeProcessStage $ProcessReceiptPath "opening_document"
        $document = $application.Documents.Open($resolvedInput, $false, $true, $false)
        Set-OfficeProcessStage $ProcessReceiptPath "document_opened"
        if (-not $TargetKind -or $TargetOrdinal -lt 1) {
            throw "DOCX_TARGET_RANGE_ARGUMENTS_INVALID"
        }
        if ($TargetKind -eq "p") {
            if ($TargetOrdinal -gt $document.Paragraphs.Count) { throw "DOCX_TARGET_PARAGRAPH_OUT_OF_RANGE" }
            $targetRange = $document.Paragraphs.Item($TargetOrdinal).Range
        }
        elseif ($TargetKind -eq "tbl") {
            if ($TargetOrdinal -gt $document.Tables.Count) { throw "DOCX_TARGET_TABLE_OUT_OF_RANGE" }
            $targetRange = $document.Tables.Item($TargetOrdinal).Range
        }
        Set-OfficeProcessStage $ProcessReceiptPath "target_range_selected"
        $resolvedPageNumber = [int]$targetRange.Information(3)
        Set-OfficeProcessStage $ProcessReceiptPath "target_page_resolved"
        if ($resolvedPageNumber -lt 1) {
            throw "DOCX_TARGET_PAGE_INVALID"
        }
        $renderDocument = $application.Documents.Add()
        $renderDocument.PageSetup.PageWidth = $document.PageSetup.PageWidth
        $renderDocument.PageSetup.PageHeight = $document.PageSetup.PageHeight
        $renderDocument.PageSetup.Orientation = $document.PageSetup.Orientation
        $renderDocument.PageSetup.TopMargin = $document.PageSetup.TopMargin
        $renderDocument.PageSetup.BottomMargin = $document.PageSetup.BottomMargin
        $renderDocument.PageSetup.LeftMargin = $document.PageSetup.LeftMargin
        $renderDocument.PageSetup.RightMargin = $document.PageSetup.RightMargin
        $renderRange = $renderDocument.Range(0, 0)
        $renderRange.FormattedText = $targetRange.FormattedText
        $locatorProof = "word_body_element_formatted_range_page"
        Set-OfficeProcessStage $ProcessReceiptPath "exporting_pdf"
        $renderDocument.ExportAsFixedFormat($resolvedOutput, 17)
        Set-OfficeProcessStage $ProcessReceiptPath "pdf_exported"
    }
    elseif ($Kind -eq "pptx") {
        [int[]]$beforeProcessIds = @(Get-Process -Name "POWERPNT" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
        $creationStartedUtc = (Get-Date).ToUniversalTime()
        $application = New-Object -ComObject PowerPoint.Application
        $application.DisplayAlerts = 1
        $application.AutomationSecurity = 3
        Write-OfficeProcessReceipt $beforeProcessIds $creationStartedUtc "POWERPNT" $ProcessReceiptPath
        $document = $application.Presentations.Open($resolvedInput, $true, $true, $false)
        $document.SaveAs($resolvedOutput, 32)
    }
    elseif ($Kind -eq "xlsx") {
        [int[]]$beforeProcessIds = @(Get-Process -Name "EXCEL" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
        $creationStartedUtc = (Get-Date).ToUniversalTime()
        $application = New-Object -ComObject Excel.Application
        $application.Visible = $false
        $application.DisplayAlerts = $false
        $application.EnableEvents = $false
        $application.AskToUpdateLinks = $false
        $application.AutomationSecurity = 3
        Write-OfficeProcessReceipt $beforeProcessIds $creationStartedUtc "EXCEL" $ProcessReceiptPath
        $document = $application.Workbooks.Open($resolvedInput, 0, $true)
        $worksheet = $document.Worksheets.Item(1)
        $worksheet.ExportAsFixedFormat(0, $resolvedOutput)
    }
    if (-not (Test-Path -LiteralPath $resolvedOutput -PathType Leaf)) {
        throw "OFFICE_PDF_NOT_CREATED"
    }
    $stream = [System.IO.File]::OpenRead($resolvedOutput)
    try {
        $header = New-Object byte[] 5
        if ($stream.Read($header, 0, 5) -ne 5) {
            throw "OFFICE_PDF_TOO_SHORT"
        }
        if ([System.Text.Encoding]::ASCII.GetString($header) -ne "%PDF-") {
            throw "OFFICE_PDF_MAGIC_INVALID"
        }
    }
    finally {
        $stream.Dispose()
    }
    [ordered]@{
        schema = "tavonel.office16_render_receipt.v1"
        status = "SUCCEEDED"
        kind = $Kind
        read_only = $true
        macros_disabled = $true
        output_size_bytes = (Get-Item -LiteralPath $resolvedOutput).Length
        output_sha256 = Get-Sha256 $resolvedOutput
        resolved_page_number = $resolvedPageNumber
        locator_proof = $locatorProof
    } | ConvertTo-Json -Depth 4 -Compress
}
finally {
    if ($null -ne $document) {
        try {
            if ($Kind -eq "docx") { $document.Close($false) }
            elseif ($Kind -eq "pptx") { $document.Close() }
            elseif ($Kind -eq "xlsx") { $document.Close($false) }
        }
        catch {}
    }
    if ($null -ne $renderDocument) {
        try { $renderDocument.Close($false) } catch {}
    }
    if ($null -ne $application) {
        try { $application.Quit() } catch {}
    }
    Release-ComObject $worksheet
    Release-ComObject $targetRange
    Release-ComObject $renderRange
    Release-ComObject $renderDocument
    Release-ComObject $document
    Release-ComObject $application
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
