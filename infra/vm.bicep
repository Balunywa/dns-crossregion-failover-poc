param name string

param location string

param subnetId string

param privateIp string

param windows bool = false

param size string = 'Standard_B2s'

param adminUsername string = 'labadmin'

@secure()

param adminPassword string

param dnsServers array = []



resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {

  name: '${name}-nsg'

  location: location

  properties: {

    securityRules: [{

      name: 'DenyInternetInbound'

      properties: {

        priority: 100

        direction: 'Inbound'

        access: 'Deny'

        protocol: '*'

        sourcePortRange: '*'

        destinationPortRange: '*'

        sourceAddressPrefix: 'Internet'

        destinationAddressPrefix: '*'

      }

    }]

  }

}

resource pip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {

  name: '${name}-egress'

  location: location

  sku: { name: 'Standard' }

  properties: { publicIPAllocationMethod: 'Static' }

}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {

  name: '${name}-nic'

  location: location

  properties: {

    networkSecurityGroup: { id: nsg.id }

    dnsSettings: { dnsServers: dnsServers }

    ipConfigurations: [{

      name: 'ip'

      properties: {

        subnet: { id: subnetId }

        privateIPAllocationMethod: 'Static'

        privateIPAddress: privateIp

        publicIPAddress: { id: pip.id }

      }

    }]

  }

}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {

  name: name

  location: location

  properties: {

    hardwareProfile: { vmSize: size }

    storageProfile: {

      imageReference: windows

        ? { publisher: 'MicrosoftWindowsServer', offer: 'WindowsServer', sku: '2022-datacenter-azure-edition', version: 'latest' }

        : { publisher: 'Canonical', offer: 'ubuntu-24_04-lts', sku: 'server', version: 'latest' }

      osDisk: { createOption: 'FromImage', managedDisk: { storageAccountType: 'StandardSSD_LRS' }, deleteOption: 'Delete' }

    }

    osProfile: {

      computerName: name

      adminUsername: adminUsername

      adminPassword: adminPassword

      windowsConfiguration: windows ? { provisionVMAgent: true, enableAutomaticUpdates: true } : null

      linuxConfiguration: windows ? null : { disablePasswordAuthentication: false, provisionVMAgent: true }

    }

    networkProfile: { networkInterfaces: [{ id: nic.id, properties: { deleteOption: 'Delete' } }] }

    diagnosticsProfile: { bootDiagnostics: { enabled: true } }

  }

}

output vmName string = vm.name

