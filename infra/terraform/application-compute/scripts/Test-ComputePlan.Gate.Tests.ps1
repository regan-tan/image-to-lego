[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $PSCommandPath
$gateScript = Join-Path $scriptDirectory "Test-ComputePlan.ps1"
$testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("image-to-lego-plan-gate-" + [guid]::NewGuid())
$recoveryImageTag = "gate-20261031-001"
New-Item -ItemType Directory -Path $testDirectory | Out-Null

function Write-PlanFixture([object[]]$changes) {
    @{ resource_changes = $changes } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fixturePath
}

function New-Change([string]$address, [string[]]$actions, [hashtable]$after = @{}) {
    return @{ mode = "managed"; address = $address; change = @{ actions = $actions; after = $after } }
}

function Invoke-Gate([string]$mode) {
    if ($mode -eq "recovery") {
        return & $gateScript `
            -PlanPath $planPath `
            -Mode $mode `
            -ExpectedApiImageTag $recoveryImageTag `
            -TerraformExecutable $terraformPath
    }
    return & $gateScript `
        -PlanPath $planPath `
        -Mode $mode `
        -TerraformExecutable $terraformPath
}

function Assert-GateRejects([string]$name, [string]$mode) {
    try {
        Invoke-Gate $mode | Out-Null
    } catch {
        return
    }
    throw "Negative $name plan-gate test unexpectedly passed."
}

try {
    $fixturePath = Join-Path $testDirectory "plan.json"
    $planPath = Join-Path $testDirectory "saved-plan.tfplan"
    $terraformPath = Join-Path $testDirectory "terraform.cmd"
    New-Item -ItemType File -Path $planPath | Out-Null
    Set-Content -LiteralPath $terraformPath -Value "@echo off`r`ntype `"%COMPUTE_PLAN_GATE_FIXTURE%`"" -NoNewline
    $env:COMPUTE_PLAN_GATE_FIXTURE = $fixturePath

    $recoveryApiAfter = @{
        site_config = @(@{
            application_stack = @(@{
                docker_image_name = "itl2b70703f.azurecr.io/image-to-lego-backend:$recoveryImageTag"
            })
        })
        app_settings = @{
            JOB_SUBMISSIONS_ENABLED = "false"
        }
    }
    $positivePlans = @{
        reconcile = @()
        destroy = @(
            (New-Change "azurerm_service_plan.api" @("delete")),
            (New-Change "azurerm_linux_web_app.api" @("delete")),
            (New-Change "azurerm_container_group.generation_worker" @("delete")),
            (New-Change "azurerm_container_group.conversion_worker" @("delete")),
            (New-Change "azurerm_container_app.frontend" @("delete"))
        )
        recovery = @(
            (New-Change "azurerm_service_plan.api" @("create")),
            (New-Change "azurerm_linux_web_app.api" @("create") $recoveryApiAfter),
            (New-Change "azurerm_container_app.frontend" @("create"))
        )
        workers = @(
            (New-Change "azurerm_container_group.generation_worker" @("create")),
            (New-Change "azurerm_container_group.conversion_worker" @("create"))
        )
    }
    foreach ($mode in $positivePlans.Keys) {
        Write-PlanFixture $positivePlans[$mode]
        $output = Invoke-Gate $mode
        if ($LASTEXITCODE -ne 0 -or $output -notmatch "PLAN_GATE_OK mode=$mode") {
            throw "Positive $mode plan-gate test failed."
        }
    }

    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $recoveryApiAfter),
        (New-Change "azurerm_resource_group.dev" @("create"))
    )
    Assert-GateRejects "unexpected-address" "recovery"

    Write-PlanFixture @(
        (New-Change "azurerm_container_group.generation_worker" @("delete", "create")),
        (New-Change "azurerm_container_group.conversion_worker" @("create"))
    )
    Assert-GateRejects "replacement" "workers"

    Write-PlanFixture @(
        (New-Change "azurerm_linux_web_app.api" @("update")),
        (New-Change "azurerm_container_group.generation_worker" @("create")),
        (New-Change "azurerm_container_group.conversion_worker" @("create"))
    )
    Assert-GateRejects "extra-update" "workers"

    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $recoveryApiAfter)
    )
    Assert-GateRejects "wrong-count" "recovery"

    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $recoveryApiAfter),
        (New-Change "azurerm_linux_web_app.api" @("create") $recoveryApiAfter)
    )
    Assert-GateRejects "duplicate-address" "recovery"

    Write-PlanFixture @(
        (New-Change "azurerm_container_group.generation_worker" @("create", "delete")),
        (New-Change "azurerm_container_group.conversion_worker" @("create"))
    )
    Assert-GateRejects "incorrect-action-order" "workers"

    $legacyApiAfter = @{
        site_config = @(@{
            application_stack = @(@{
                docker_image_name = "itl2b70703f.azurecr.io/image-to-lego-backend:dev-20261029-205014"
            })
        })
    }
    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $legacyApiAfter),
        (New-Change "azurerm_container_app.frontend" @("create"))
    )
    Assert-GateRejects "legacy-api-image" "recovery"

    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create")),
        (New-Change "azurerm_container_app.frontend" @("create"))
    )
    Assert-GateRejects "missing-api-image" "recovery"

    $missingPauseSettingAfter = @{
        site_config = @(@{
            application_stack = @(@{
                docker_image_name = "itl2b70703f.azurecr.io/image-to-lego-backend:$recoveryImageTag"
            })
        })
        app_settings = @{}
    }
    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $missingPauseSettingAfter),
        (New-Change "azurerm_container_app.frontend" @("create"))
    )
    Assert-GateRejects "missing-pause-setting" "recovery"

    $enabledPauseSettingAfter = @{
        site_config = @(@{
            application_stack = @(@{
                docker_image_name = "itl2b70703f.azurecr.io/image-to-lego-backend:$recoveryImageTag"
            })
        })
        app_settings = @{
            JOB_SUBMISSIONS_ENABLED = "true"
        }
    }
    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $enabledPauseSettingAfter),
        (New-Change "azurerm_container_app.frontend" @("create"))
    )
    Assert-GateRejects "enabled-pause-setting" "recovery"

    $invalidPauseSettingAfter = @{
        site_config = @(@{
            application_stack = @(@{
                docker_image_name = "itl2b70703f.azurecr.io/image-to-lego-backend:$recoveryImageTag"
            })
        })
        app_settings = @{
            JOB_SUBMISSIONS_ENABLED = $false
        }
    }
    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        (New-Change "azurerm_linux_web_app.api" @("create") $invalidPauseSettingAfter),
        (New-Change "azurerm_container_app.frontend" @("create"))
    )
    Assert-GateRejects "invalid-pause-setting" "recovery"

    $unknownPauseSettingAfter = @{
        site_config = @(@{
            application_stack = @(@{
                docker_image_name = "itl2b70703f.azurecr.io/image-to-lego-backend:$recoveryImageTag"
            })
        })
        app_settings = @{
            JOB_SUBMISSIONS_ENABLED = "false"
        }
    }
    $unknownPauseSettingChange = New-Change "azurerm_linux_web_app.api" @("create") $unknownPauseSettingAfter
    $unknownPauseSettingChange.change.after_unknown = @{
        app_settings = @{
            JOB_SUBMISSIONS_ENABLED = $true
        }
    }
    Write-PlanFixture @(
        (New-Change "azurerm_service_plan.api" @("create")),
        $unknownPauseSettingChange,
        (New-Change "azurerm_container_app.frontend" @("create"))
    )
    Assert-GateRejects "unknown-pause-setting" "recovery"

    "not-json" | Set-Content -LiteralPath $fixturePath
    Assert-GateRejects "malformed-json" "reconcile"

    Set-Content -LiteralPath $terraformPath -Value "@echo off`r`nexit /b 1" -NoNewline
    Assert-GateRejects "terraform-failure" "reconcile"

    Write-Output "PLAN_GATE_TESTS_OK positive=4 negative=14"
} finally {
    Remove-Item -LiteralPath $testDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
