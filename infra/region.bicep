param location string

param prefix string

param addressPrefix string

param inboundPrefix string

param outboundPrefix string

param serverPrefix string

param inboundIp string

param upstreamIp string



resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {

  name: '${prefix}-hub'

  location: location

  properties: {

    addressSpace: { addressPrefixes: [addressPrefix] }

    subnets: [

      {

        name: 'inbound'

        properties: {

          addressPrefix: inboundPrefix

          delegations: [{ name: 'resolver', properties: { serviceName: 'Microsoft.Network/dnsResolvers' } }]

        }

      }

      {

        name: 'outbound'

        properties: {

          addressPrefix: outboundPrefix

          delegations: [{ name: 'resolver', properties: { serviceName: 'Microsoft.Network/dnsResolvers' } }]

        }

      }

      { name: 'servers', properties: { addressPrefix: serverPrefix } }

    ]

  }

}

resource resolver 'Microsoft.Network/dnsResolvers@2022-07-01' = {

  name: '${prefix}-resolver'

  location: location

  properties: { virtualNetwork: { id: vnet.id } }

}

resource inbound 'Microsoft.Network/dnsResolvers/inboundEndpoints@2022-07-01' = {

  parent: resolver

  name: 'inbound'

  location: location

  properties: {

    ipConfigurations: [{

      privateIpAllocationMethod: 'Static'

      privateIpAddress: inboundIp

      subnet: { id: '${vnet.id}/subnets/inbound' }

    }]

  }

}

resource outbound 'Microsoft.Network/dnsResolvers/outboundEndpoints@2022-07-01' = {

  parent: resolver

  name: 'outbound'

  location: location

  properties: { subnet: { id: '${vnet.id}/subnets/outbound' } }

}

resource ruleset 'Microsoft.Network/dnsForwardingRulesets@2022-07-01' = {

  name: '${prefix}-ruleset'

  location: location

  properties: { dnsResolverOutboundEndpoints: [{ id: outbound.id }] }

}

resource rule 'Microsoft.Network/dnsForwardingRulesets/forwardingRules@2022-07-01' = {

  parent: ruleset

  name: 'lab'

  properties: {

    domainName: 'lab.failover.test.'

    forwardingRuleState: 'Enabled'

    targetDnsServers: [{ ipAddress: upstreamIp, port: 53 }]

  }

}

resource link 'Microsoft.Network/dnsForwardingRulesets/virtualNetworkLinks@2022-07-01' = {

  parent: ruleset

  name: 'hub'

  properties: { virtualNetwork: { id: vnet.id } }

}

output vnetId string = vnet.id

output serverSubnetId string = '${vnet.id}/subnets/servers'

output rulesetId string = ruleset.id

output inboundAddress string = inbound.properties.ipConfigurations[0].privateIpAddress

