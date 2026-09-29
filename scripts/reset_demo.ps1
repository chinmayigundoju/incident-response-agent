param([string]$ApiBaseUrl = 'http://localhost:8000')

$result = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/v1/demo/reset"
Write-Host "Scenario: $($result.scenario)"
Write-Host "State: $($result.state)"
