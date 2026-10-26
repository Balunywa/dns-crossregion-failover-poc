@secure()

param adminPassword string

param eastSize string = 'Standard_B2s'

param westSize string = 'Standard_B2s'

param storageName string = 'dnsproof${uniqueString(resourceGroup().id)}'



module east 'region.bicep' = {

  name: 'east-network'

  params: {

    location: 'eastus'

    prefix: 'dnspoc-east'

    addressPrefix: '10.10.0.0/16'

    inboundPrefix: '10.10.0.0/28'

    outboundPrefix: '10.10.1.0/28'

    serverPrefix: '10.10.2.0/24'

    inboundIp: '10.10.0.4'

    upstreamIp: '10.10.2.4'

  }

}

module west 'region.bicep' = {

  name: 'west-network'

  params: {

    location: 'westus'

    prefix: 'dnspoc-west'

    addressPrefix: '10.30.0.0/16'

    inboundPrefix: '10.30.0.0/28'

    outboundPrefix: '10.30.1.0/28'

    serverPrefix: '10.30.2.0/24'

    inboundIp: '10.30.0.4'

    upstreamIp: '10.30.2.4'

  }

}

resource spoke 'Microsoft.Network/virtualNetworks@2024-05-01' = {

  name: 'dnspoc-east-spoke'

  location: 'eastus'

  properties: {

    addressSpace: { addressPrefixes: ['10.20.0.0/16'] }

    subnets: [{ name: 'clients', properties: { addressPrefix: '10.20.0.0/24' } }]

  }

}

resource eastHub 'Microsoft.Network/virtualNetworks@2024-05-01' existing = { name: 'dnspoc-east-hub' }

resource westHub 'Microsoft.Network/virtualNetworks@2024-05-01' existing = { name: 'dnspoc-west-hub' }

resource spokeToEast 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {

  parent: spoke

  name: 'to-east'

  properties: { remoteVirtualNetwork: { id: east.outputs.vnetId }, allowVirtualNetworkAccess: true }

}

resource eastToSpoke 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {

  parent: eastHub

  name: 'to-spoke'

  properties: { remoteVirtualNetwork: { id: spoke.id }, allowVirtualNetworkAccess: true }

  dependsOn: [east]

}

resource spokeToWest 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {

  parent: spoke

  name: 'to-west'

  properties: { remoteVirtualNetwork: { id: west.outputs.vnetId }, allowVirtualNetworkAccess: true }

  dependsOn: [spokeToEast]

}

resource westToSpoke 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2024-05-01' = {

  parent: westHub

  name: 'to-spoke'

  properties: { remoteVirtualNetwork: { id: spoke.id }, allowVirtualNetworkAccess: true }

  dependsOn: [west]

}

resource eastRuleset 'Microsoft.Network/dnsForwardingRulesets@2022-07-01' existing = { name: 'dnspoc-east-ruleset' }

resource spokeLink 'Microsoft.Network/dnsForwardingRulesets/virtualNetworkLinks@2022-07-01' = {

  parent: eastRuleset

  name: 'east-spoke'

  properties: { virtualNetwork: { id: spoke.id } }

  dependsOn: [east]

}

module clients 'vm.bicep' = [for client in [

  { name: 'dnspoc-win', ip: '10.20.0.4', windows: true }

  { name: 'dnspoc-ubuntu', ip: '10.20.0.5', windows: false }

]: {

  name: client.name

  params: {

    name: client.name

    location: 'eastus'

    subnetId: '${spoke.id}/subnets/clients'

    privateIp: client.ip

    windows: client.windows

    size: eastSize

    adminPassword: adminPassword

    dnsServers: ['168.63.129.16', west.outputs.inboundAddress]

  }

}]

module upstreamEast 'vm.bicep' = {

  name: 'upstream-east'

  params: {

    name: 'dnspoc-up-east'

    location: 'eastus'

    subnetId: east.outputs.serverSubnetId

    privateIp: '10.10.2.4'

    adminPassword: adminPassword

    size: eastSize

  }

}

module upstreamWest 'vm.bicep' = {

  name: 'upstream-west'

  params: {

    name: 'dnspoc-up-west'

    location: 'westus'

    subnetId: west.outputs.serverSubnetId

    privateIp: '10.30.2.4'

    adminPassword: adminPassword

    size: westSize

  }

}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {

  name: storageName

  location: 'eastus'

  sku: { name: 'Standard_LRS' }

  kind: 'StorageV2'

  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false, supportsHttpsTrafficOnly: true }

}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = { parent: storage, name: 'default' }

resource evidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {

  parent: blobService

  name: 'evidence'

  properties: { publicAccess: 'None' }

}

output storageAccount string = storage.name

output primary string = '168.63.129.16'

output secondary string = west.outputs.inboundAddress

output clientVms array = ['dnspoc-win', 'dnspoc-ubuntu']

