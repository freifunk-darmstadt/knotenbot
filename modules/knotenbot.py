#!/usr/bin/env python
import sopel
import requests
from sopel.config.types import StaticSection, ValidatedAttribute, ListAttribute
from sopel.formatting import bold, color, colors
knoten_url = 'https://map.darmstadt.freifunk.net/data/nodes.json'


class KnotenbotSection(StaticSection):
    channel = ValidatedAttribute('channel', str, default='#ffda-log')
    url = ValidatedAttribute('url', str, default=knoten_url)


def get_data(bot):
    response = requests.get(knoten_url)
    if response.status_code == 200:
        return response.json()['nodes']

    return None


def preprocess_data(nodes):
    return dict((v['nodeinfo']['hostname'], dict(flags=v['flags'], network=v['nodeinfo']['network'], software=v['nodeinfo']['software']))
                for v in nodes)


def setup(bot):
    bot.config.define_section('knotenbot', KnotenbotSection)

    if not 'knoten' in bot.memory:
        bot.memory['knoten'] = {}


def new_node(bot, node, info):
    addr = info['network'].get('addresses', None)
    if not addr:
        addr = 'N/A'
    else:
        addr = addr[-1]
    try:
        version = info['software']['firmware']['release']
    except KeyError:
        version = 'N/A'
    bot.msg('#ffda-log', '{} is {}. - {} - http://[{}]'.format(node, bold(color('new', colors.BLUE)), version, addr))


ONLINE = bold(color('online', colors.GREEN))
OFFLINE = bold(color('offline', colors.RED))

def status_changed(bot, node, info):
    status = {True: ONLINE, False: OFFLINE}[info['flags']['online']]
    addr = info['network'].get('addresses', None)
    if not addr:
        addr = 'N/A'
    else:
        addr = sorted(addr)[0]
    try:
        version = info['software']['firmware']['release']
    except KeyError:
        version = 'N/A'
    bot.msg('#ffda-log', '{} is now {}. - {} - http://[{}]'.format(node, status, version, addr))


def diff_status(data, old_data):
    new, changed = [], []
    for node, info in data.items():
        old = old_data.get(node, None)
        if old:
            if old['flags']['online'] != info['flags']['online']:
                changed.append((node, info))
        else:
            if info['flags']['online']:
                new.append((node, info))

    return new, changed


@sopel.module.interval(30)
def update_data(bot):
    data = preprocess_data(get_data(bot))

    old_data = bot.memory['knoten']

    new, changed = diff_status(data, old_data)

    for node, info in new[:10]:
        new_node(bot, node, info)
    if len(new) > 10:
        bot.msg('#ffda-log', ' ... and {} more'.format(len(new) - 10))

    for node, info in changed[:10]:
        status_changed(bot, node, info)

    if len(changed) > 10:
        bot.msg('#ffda-log', ' ... and {} moaddressesre'.format(len(changed) - 10))

    bot.memory['knoten'] = data
