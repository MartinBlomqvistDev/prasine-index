#!/usr/bin/env pwsh
# Rerun all company assessments at max-claims 1, sequentially.
# Cost estimate: ~$1.45 total. Do not run in parallel.

$python = "c:\prasine-index\.venv\Scripts\python.exe"
$script = "scripts\run_assessment.py"

$companies = @(
    @{ name = "BP plc";                    url = "https://www.bp.com/en/global/corporate/sustainability/getting-to-net-zero.html" },
    @{ name = "RWE AG";                    url = "https://www.rwe.com/en/responsibility-and-sustainability/environmental-protection/climate" },
    @{ name = "Danone SA";                 url = "https://www.danone.com/sustainability/nature/driving-climate-action.html" },
    @{ name = "Eni SpA";                   url = "https://www.eni.com/en-IT/sustainability/decarbonization.html" },
    @{ name = "SSAB AB";                   url = "https://www.ssab.com/en/brands-and-products/strenx/sustainability" },
    @{ name = "IKEA Group";                url = "https://www.ikea.com/us/en/this-is-ikea/climate-environment/" },
    @{ name = "Enel SpA";                  url = "https://www.enel.com/investors/sustainability" },
    @{ name = "H&M Group";                 url = "https://hmgroup.com/sustainability/circularity-and-climate/climate" },
    @{ name = "Securitas AB";              url = "https://www.securitas.com/en/sustainability/sustainability-strategic-pillars" },
    @{ name = "Glencore plc";             url = "https://www.glencore.com/sustainability/esg-a-z" },
    @{ name = "Orsted A/S";               url = "https://orsted.com/en/about-us/sustainability" },
    @{ name = "KLM Royal Dutch Airlines"; url = "https://www.klm.com/information/sustainability" },
    @{ name = "Wizz Air Holdings plc";    url = "https://wizzair.com/en-gb/information-and-services/investor-relations/investors/annual-reports" },
    @{ name = "Ryanair Holdings plc";     url = "https://corporate.ryanair.com/sustainability/" },
    @{ name = "LKAB";                      url = "https://www.lkab.com/en/sustainability/" },
    @{ name = "Oresundskraft";             url = "https://www.oresundskraft.se/ccs" },
    @{ name = "Stegra";                    url = "https://www.stegra.com/en/green-hydrogen" },
    @{ name = "TotalEnergies SE";         url = "https://totalenergies.com/sustainability/climate-and-sustainable-energy/reducing-our-emissions" }
)

$total = $companies.Count
$i = 0

foreach ($c in $companies) {
    $i++
    Write-Host "`n[$i/$total] $($c.name)" -ForegroundColor Cyan
    & $python $script --company $c.name --url $c.url --max-claims 1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAILED] $($c.name) — continuing" -ForegroundColor Red
    }
}

Write-Host "`nDone. $total companies processed." -ForegroundColor Green
