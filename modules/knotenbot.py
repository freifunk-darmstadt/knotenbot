#!/usr/bin/env python
import re
import sopel
import requests
from datetime import datetime, timedelta
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
    return dict((v['nodeinfo']['node_id'], dict(flags=v['flags'], network=v['nodeinfo']['network'],
                                                 software=v['nodeinfo']['software'], statistics=v['statistics'],
                                                 lastseen=v['lastseen'], hostname=v['nodeinfo']['hostname'],
                                                 model=v['nodeinfo'].get('hardware', {}).get('model', 'N/A')))
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
    bot.msg('#ffda-log', '{} is {}. - {} - http://[{}]'.format(info['hostname'], bold(color('new', colors.BLUE)), version, addr))


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
    bot.msg('#ffda-log', '{} is now {}. - {} - http://[{}]'.format(info['hostname'], status, version, addr))


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

def find_node(bot, nodename):
    if type(bot.memory['knoten']) is not dict or len(bot.memory['knoten'].keys()) is 0:
        return None

    if len(re.findall('^([0-9A-Fa-f]{2}([:-])?){5}([0-9A-Fa-f]{2})$', nodename)) is 1:
        nodes = [bot.memory['knoten'][node] for node in bot.memory['knoten']
                 if bot.memory['knoten'][node]['network']['mac'].replace(':', '').lower() == nodename.replace(':', '').lower()]
        if len(nodes) is 1:
            return nodes

    return [bot.memory['knoten'][node] for node in bot.memory['knoten']
            if nodename.lower() in bot.memory['knoten'][node]['hostname'].lower()]

def format_time(time):
    time_difference = datetime.now() - time
    total_minutes = time_difference.total_seconds() / 60
    days = total_minutes / (60*24)
    hours = (total_minutes - int(days)*60*24) / 60
    minutes = total_minutes - int(days)*60*24 - int(hours)*60

    if days >= 1:
        return "{}d {}h {}m".format(int(days), int(hours), int(minutes))
    elif hours >= 1:
        return "{}h {}m".format(int(hours), int(minutes))
    else:
        return "{}m".format(int(minutes))

def color_percentage(val):
    if val >= 90:
        return color(str(val), colors.RED)
    else:
        return color(str(val), colors.GREEN)

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
        bot.msg('#ffda-log', ' ... and {} more addresses'.format(len(changed) - 10))

    bot.memory['knoten'] = data

@sopel.module.commands('nodeinfo')
def nodeinfo(bot, trigger):
    search_queries = [n for n in trigger.args[1].split(' ')[1:] if len(n) > 0]
    if len(search_queries) is 0:
        bot.msg(trigger.sender, "Usage: .nodeinfo [nodename]")
    for node in search_queries[:2]:
        possible_nodes = find_node(bot, node)
        if possible_nodes is None:
            bot.msg(trigger.sender, "No Data yet")
            break
        elif len(possible_nodes) is 0:
            bot.msg(trigger.sender, "No node with Name {}".format(node))
        elif len(possible_nodes) is 1:
            node = possible_nodes[0]
            online = node['flags']['online']
            time = datetime.strptime(node['lastseen'], '%Y-%m-%dT%H:%M:%S.%fZ')
            nodename = bold(color(node['hostname'], colors.RED))
            if online:
                nodename = bold(color(node['hostname'], colors.GREEN))
                time = datetime.now() - timedelta(seconds=node['statistics']['uptime'])

            addr = node['network'].get('addresses', None)
            if not addr:
                addr = 'N/A'
            else:
                addr = "http://[{}]".format(sorted(addr)[0])
            bot.msg(trigger.sender, "{}: {} - {} - {}({})".format(nodename,
                                                                  format_time(time),
                                                                  node['model'],
                                                                  node['software']['firmware']['release'],
                                                                  node['software']['firmware']['base']))
            if online:
                bot.msg(trigger.sender,
                        "Load: {} - Memory: {} - Filesystem: {} - {}".format(
                            color_percentage(int(round(node['statistics'].get('loadavg', 0) * 100))),
                            color_percentage(round(node['statistics'].get('memory_usage', 0) * 100, 2)),
                            color_percentage(round(node['statistics'].get('rootfs_usage', 0) * 100, 2)),
                            addr))
        elif len(possible_nodes) > 1:
            max_full_hostnames = 3
            msg_string = ", ".join(map(lambda x: x['hostname'], possible_nodes[:max_full_hostnames]))
            if(len(possible_nodes) > max_full_hostnames):
                msg_string = msg_string + " and {} more".format(len(possible_nodes)-max_full_hostnames)
            bot.msg(trigger.sender, "More than one node containing '{}': {}".format(node, msg_string))