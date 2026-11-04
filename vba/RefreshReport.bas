Attribute VB_Name = "RefreshReport"
'==============================================================================
' RefreshReport.bas  --  Campaign_AB_Test_Audit
'------------------------------------------------------------------------------
' PURPOSE
'   Refresh the live-formula Excel report from fresh CSV exports, validate it,
'   recalculate, and publish the Summary tab to PDF -- but REFUSE to publish if
'   any integrity check fails.
'
' WHAT IT DOES
'   1. Reloads the raw aggregates on the "Data" tab from fresh CSV exports:
'        - overall counts (Data!B4:B8) from outputs/overall_counts.csv
'        - per-band counts from outputs/exposure_bands.csv (matched by header name,
'          so CSV column order does not matter); leftover band rows are cleared if
'          the new CSV has fewer bands.
'   2. Integrity checks:
'        - every reloaded count is present (non-blank) and >= 0
'        - every conversion rate on Summary / Exposure is within [0, 1]
'      If any check fails: show a MsgBox and EXIT without publishing.
'   3. Forces a full recalculation (Application.CalculateFull).
'   4. Exports the "Summary" sheet to a PDF next to the workbook.
'
' HOW TO IMPORT (Excel for Windows / Mac)
'   File > Options > Customize Ribbon > enable "Developer".
'   Developer > Visual Basic > File > Import File... > select this .bas file.
'   Close the editor. Developer > Macros > RefreshReport > Run.
'
' NOTE (honesty): this macro was NOT executed in the build environment (no
'   automatable Excel available). It is shipped and verified by code review only.
'   See AI_USE.md.
'==============================================================================
Option Explicit

Private Const DATA_SHEET As String = "Data"
Private Const SUMMARY_SHEET As String = "Summary"
Private Const EXPOSURE_SHEET As String = "Exposure"
Private Const FIRST_BAND_ROW As Long = 12       ' Data tab: first per-band row
Private Const EXPO_FIRST_ROW As Long = 3        ' Exposure tab: first data row

Public Sub RefreshReport()
    Dim wb As Workbook
    Set wb = ThisWorkbook

    ' --- 1a. Reload overall counts (Data!B4:B8) from overall_counts.csv --------
    Dim overallPath As String
    overallPath = wb.Path & Application.PathSeparator & "overall_counts.csv"
    If Dir(overallPath) = "" Then
        MsgBox "Refresh aborted: CSV not found at " & overallPath, vbCritical, "RefreshReport"
        Exit Sub
    End If
    If Not ReloadOverallFromCsv(wb.Worksheets(DATA_SHEET), overallPath) Then
        MsgBox "Refresh aborted: could not parse " & overallPath, vbCritical, "RefreshReport"
        Exit Sub
    End If

    ' --- 1b. Reload per-band aggregates from exposure_bands.csv ----------------
    Dim csvPath As String
    csvPath = wb.Path & Application.PathSeparator & "exposure_bands.csv"
    If Dir(csvPath) = "" Then
        MsgBox "Refresh aborted: CSV not found at " & csvPath, vbCritical, "RefreshReport"
        Exit Sub
    End If

    If Not ReloadBandsFromCsv(wb.Worksheets(DATA_SHEET), csvPath) Then
        MsgBox "Refresh aborted: could not parse " & csvPath, vbCritical, "RefreshReport"
        Exit Sub
    End If

    ' --- 2. Force a full recalculation BEFORE validating derived rates ---------
    Application.CalculateFull

    ' --- 3. Integrity checks --------------------------------------------------
    Dim problem As String
    problem = ValidateReport(wb)
    If Len(problem) > 0 Then
        MsgBox "Refresh REFUSED to publish:" & vbCrLf & problem, vbCritical, "RefreshReport"
        Exit Sub
    End If

    ' --- 4. Publish the Summary tab to PDF ------------------------------------
    Dim pdfPath As String
    pdfPath = wb.Path & Application.PathSeparator & "Campaign_Test_Summary.pdf"
    wb.Worksheets(SUMMARY_SHEET).ExportAsFixedFormat Type:=xlTypePDF, Filename:=pdfPath, _
        Quality:=xlQualityStandard, IncludeDocProperties:=False, OpenAfterPublish:=False

    MsgBox "Refresh complete. All checks passed." & vbCrLf & _
           "Summary exported to: " & pdfPath, vbInformation, "RefreshReport"
End Sub

'------------------------------------------------------------------------------
' Load the single overall-counts row (matched by header name) into Data!B4:B8:
'   n_ad -> B4, conv_ad -> B5, n_psa -> B6, conv_psa -> B7, total_ad_impressions -> B8
'------------------------------------------------------------------------------
Private Function ReloadOverallFromCsv(ws As Worksheet, csvPath As String) As Boolean
    On Error GoTo Fail
    Dim fnum As Integer, line As String
    Dim headers() As String, parts() As String
    Dim colN_ad As Long, colConv_ad As Long, colN_psa As Long
    Dim colConv_psa As Long, colImpr As Long
    Dim i As Long

    ' Cross-platform header matching (Select Case) -- no Scripting.Dictionary,
    ' which does NOT exist in Excel for Mac.
    colN_ad = -1: colConv_ad = -1: colN_psa = -1: colConv_psa = -1: colImpr = -1

    fnum = FreeFile
    Open csvPath For Input As #fnum
    Line Input #fnum, line
    headers = Split(line, ",")
    For i = LBound(headers) To UBound(headers)
        Select Case Trim(headers(i))
            Case "n_ad": colN_ad = i
            Case "conv_ad": colConv_ad = i
            Case "n_psa": colN_psa = i
            Case "conv_psa": colConv_psa = i
            Case "total_ad_impressions": colImpr = i
        End Select
    Next i
    If colN_ad < 0 Or colConv_ad < 0 Or colN_psa < 0 _
       Or colConv_psa < 0 Or colImpr < 0 Then GoTo Fail

    Line Input #fnum, line
    parts = Split(line, ",")
    ws.Cells(4, 2).Value = CDbl(parts(colN_ad))          ' B4: n_ad
    ws.Cells(5, 2).Value = CDbl(parts(colConv_ad))       ' B5: conv_ad
    ws.Cells(6, 2).Value = CDbl(parts(colN_psa))         ' B6: n_psa
    ws.Cells(7, 2).Value = CDbl(parts(colConv_psa))      ' B7: conv_psa
    ws.Cells(8, 2).Value = CDbl(parts(colImpr))          ' B8: total_ad_impressions

    Close #fnum
    ReloadOverallFromCsv = True
    Exit Function
Fail:
    On Error Resume Next
    Close #fnum
    ReloadOverallFromCsv = False
End Function

'------------------------------------------------------------------------------
' Load n_ad / conv_ad / n_psa / conv_psa / ad_impressions columns from the CSV
' (matched by header name) into the Data tab per-band block. Returns True on OK.
' Clears any leftover band rows if the new CSV has fewer bands than before.
'------------------------------------------------------------------------------
Private Function ReloadBandsFromCsv(ws As Worksheet, csvPath As String) As Boolean
    On Error GoTo Fail
    Dim fnum As Integer, line As String
    Dim headers() As String, parts() As String
    Dim colBand As Long, colN_ad As Long, colConv_ad As Long, colN_psa As Long
    Dim colConv_psa As Long, colImpr As Long
    Dim rowIdx As Long

    colBand = -1: colN_ad = -1: colConv_ad = -1
    colN_psa = -1: colConv_psa = -1: colImpr = -1

    fnum = FreeFile
    Open csvPath For Input As #fnum

    ' Header row -> find column indexes by name.
    Line Input #fnum, line
    headers = Split(line, ",")
    Dim i As Long
    For i = LBound(headers) To UBound(headers)
        Select Case Trim(headers(i))
            Case "band": colBand = i
            Case "n_ad": colN_ad = i
            Case "conv_ad": colConv_ad = i
            Case "n_psa": colN_psa = i
            Case "conv_psa": colConv_psa = i
            Case "ad_impressions": colImpr = i
        End Select
    Next i

    If colBand < 0 Or colN_ad < 0 Or colConv_ad < 0 Or colN_psa < 0 _
       Or colConv_psa < 0 Or colImpr < 0 Then GoTo Fail

    rowIdx = FIRST_BAND_ROW
    Do While Not EOF(fnum)
        Line Input #fnum, line
        If Len(Trim(line)) > 0 Then
            parts = Split(line, ",")
            ws.Cells(rowIdx, 1).Value = Trim(parts(colBand))      ' A: band label
            ws.Cells(rowIdx, 2).Value = CDbl(parts(colN_ad))      ' B: n_ad
            ws.Cells(rowIdx, 3).Value = CDbl(parts(colConv_ad))   ' C: conv_ad
            ws.Cells(rowIdx, 4).Value = CDbl(parts(colN_psa))     ' D: n_psa
            ws.Cells(rowIdx, 5).Value = CDbl(parts(colConv_psa))  ' E: conv_psa
            ws.Cells(rowIdx, 6).Value = CDbl(parts(colImpr))      ' F: ad_impressions
            rowIdx = rowIdx + 1
        End If
    Loop
    Close #fnum

    ' Clear any leftover band rows from a previous (longer) refresh.
    Do While Len(ws.Cells(rowIdx, 1).Text) > 0
        ws.Range(ws.Cells(rowIdx, 1), ws.Cells(rowIdx, 6)).ClearContents
        rowIdx = rowIdx + 1
    Loop

    ReloadBandsFromCsv = True
    Exit Function
Fail:
    On Error Resume Next
    Close #fnum
    ReloadBandsFromCsv = False
End Function

'------------------------------------------------------------------------------
' Return "" if the report is publishable, else a human-readable problem string.
'------------------------------------------------------------------------------
Private Function ValidateReport(wb As Workbook) As String
    Dim dataWs As Worksheet, sumWs As Worksheet, expoWs As Worksheet
    Set dataWs = wb.Worksheets(DATA_SHEET)
    Set sumWs = wb.Worksheets(SUMMARY_SHEET)
    Set expoWs = wb.Worksheets(EXPOSURE_SHEET)

    Dim r As Long, c As Long, v As Variant

    ' Overall counts (Data!B4:B8) must be present and non-negative.
    For r = 4 To 8
        v = dataWs.Cells(r, 2).Value
        If Len(dataWs.Cells(r, 2).Text) = 0 Then
            ValidateReport = "Missing count at Data!B" & r: Exit Function
        End If
        If Not IsNumeric(v) Then
            ValidateReport = "Non-numeric count at Data!B" & r: Exit Function
        End If
        If v < 0 Then ValidateReport = "Negative count at Data!B" & r: Exit Function
    Next r

    ' Per-band counts (Data!B..F from FIRST_BAND_ROW) non-blank and non-negative.
    r = FIRST_BAND_ROW
    Do While Len(dataWs.Cells(r, 1).Text) > 0
        For c = 2 To 6
            v = dataWs.Cells(r, c).Value
            If Len(dataWs.Cells(r, c).Text) = 0 Or Not IsNumeric(v) Then
                ValidateReport = "Bad per-band count at Data row " & r: Exit Function
            End If
            If v < 0 Then ValidateReport = "Negative per-band count at Data row " & r: Exit Function
        Next c
        r = r + 1
    Loop

    ' Summary conversion rates (D4, D5) must be within [0, 1].
    If Not RateInRange(sumWs.Range("D4").Value) Then
        ValidateReport = "Summary ad rate out of [0,1]": Exit Function
    End If
    If Not RateInRange(sumWs.Range("D5").Value) Then
        ValidateReport = "Summary psa rate out of [0,1]": Exit Function
    End If

    ' Exposure per-band rates (columns D and G) must be within [0, 1].
    r = EXPO_FIRST_ROW
    Do While Len(expoWs.Cells(r, 1).Text) > 0
        If Not RateInRange(expoWs.Cells(r, 4).Value) Then
            ValidateReport = "Exposure ad rate out of [0,1] at row " & r: Exit Function
        End If
        If Not RateInRange(expoWs.Cells(r, 7).Value) Then
            ValidateReport = "Exposure psa rate out of [0,1] at row " & r: Exit Function
        End If
        r = r + 1
    Loop

    ValidateReport = ""   ' all checks passed
End Function

Private Function RateInRange(v As Variant) As Boolean
    RateInRange = IsNumeric(v)
    If RateInRange Then RateInRange = (v >= 0 And v <= 1)
End Function
