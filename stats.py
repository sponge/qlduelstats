import os, glob, json, sys, csv, pickle
import requests

class EmptySteamException(Exception):
    pass

def process_match(f):
    events = json.load(open(f, "r", encoding='UTF-8'))

    started_ev = [x for x in events if x['event']['TYPE'] == 'MATCH_STARTED']
    if len(started_ev) != 1:
        raise Exception("match has no/too many start events start events", f)

    players = [x for x in started_ev[0]['event']['DATA']['PLAYERS'] if x['TEAM'] == 0]

    if str(players[0]['STEAM_ID']) == '0' or str(players[1]['STEAM_ID']) == '0':
        raise EmptySteamException("match has a player with a steam id of 0", f)

    if len(players) != 2:
       raise Exception("didn't find 2 players in the match:", len(players), f)

    idx = { players[0]['STEAM_ID']: 0, players[1]['STEAM_ID']: 1 }
    scores = [0,0]

    mstats = {
        'id0': players[0]['STEAM_ID'],
        'id1': players[1]['STEAM_ID'],
        'score0': 0,
        'score1': 0,
        'lastTieTime': 0,
        'lastTieScore': 0,
        'leadChanges': 0,
        'netDifference': 0,
        'firstFragWon': 0,
        'higherEloWon': 0,
        'mapName': started_ev[0]['event']['DATA']['MAP']
    }

    firstFragger = None

    deaths = [x['event']['DATA'] for x in events if x['event']['TYPE'] == 'PLAYER_DEATH']
    for d in deaths:
        if d['WARMUP'] == True:
            continue

        if scores[0] == scores[1]:
            if scores[0] != 0:
                mstats['leadChanges'] += 1
            mstats['lastTieTime'] = d['TIME']
            mstats['lastTieScore'] = scores[0]
        if d['KILLER'] == None:
            i = idx[d['VICTIM']['STEAM_ID']]
            scores[i]+= -1
        else:
            i = idx[d['KILLER']['STEAM_ID']]
            scores[i] += 1
            if firstFragger == None:
                firstFragger = i

    if firstFragger != None:
        otherFragger = 0 if firstFragger == 1 else 1
        if scores[firstFragger] > scores[otherFragger]:
            mstats['firstFragWon'] = 1

    mstats['netDifference'] = abs(scores[0] - scores[1])
    mstats['score0'] = scores[0]
    mstats['score1'] = scores[1]
    return mstats

if __name__ == "__main__":
    matches = glob.glob("json/*.json")
    print("got {0} matches to process".format(len(matches)))

    summary_stats = []

    elo_cache = {}
    if os.path.isfile('steamids.pickle'):
        elo_cache = pickle.load(open("steamids.pickle", "rb"))
        print("loaded {0} players from steam id cache".format(len(elo_cache)))

    for f in matches:
        try:
            m = process_match(f)
            summary_stats.append(m)
        except EmptySteamException:
            continue
        except Exception as err:
            print("Exception:", err, f)
            continue

    # get all unique steam ids
    steam_ids = []
    steam_ids.extend([x['id0'] for x in summary_stats])
    steam_ids.extend([x['id1'] for x in summary_stats])
    steam_ids = list(set(steam_ids))

    # find all elos we don't have cached and grab them
    uncached_ids = [x for x in steam_ids if x not in elo_cache]
    while len(uncached_ids) > 0:
        print('grabbing elo scores, {0} remaining'.format(len(uncached_ids)))
        url = 'http://qlstats.net/elo/' + '+'.join(uncached_ids[0:100])
        r = requests.get(url)
        players = r.json()
        for player in players['players']:
            if 'duel' in player:
                elo_cache[player['steamid']] = player['duel']
        
        uncached_ids = uncached_ids[100:]
    # save them to the disk
    pickle.dump(elo_cache, open('steamids.pickle', 'wb'))

    # loop back through summary_stats and add elo0 and elo1 columns
    for m in summary_stats:
        if m['id0'] not in elo_cache:
            print("Missed id0 in elo cache", m['id0'])
            continue

        if m['id1'] not in elo_cache:
            print("Missed id1 in elo cache", m['id1'])
            continue

        m['games0'] = elo_cache[ m['id0'] ]['games']
        m['games1'] = elo_cache[ m['id1'] ]['games']

        m['elo0'] = elo_cache[ m['id0'] ]['elo']
        m['elo1'] = elo_cache[ m['id1'] ]['elo']

        m['eloDiff'] = abs(m['elo0'] - m['elo1'])

        if (m['score0'] > m['score1'] and m['elo0'] > m['elo1'] ) or (m['score0'] < m['score1'] and m['elo0'] < m['elo1']):
            m['higherEloWon'] = 1

        del m['id0']
        del m['id1']

    print("parsed matches:", len(summary_stats))
    print("elo cache count:", len(elo_cache))
    i = 0
    with open("stats.csv", "w") as f:
        writer = csv.DictWriter(f, extrasaction='ignore', lineterminator='\n', fieldnames=['score0', 'score1', 'lastTieTime', 'leadChanges', 'netDifference', 'eloDiff', 'elo0', 'elo1', 'games0', 'games1', 'firstFragWon', 'higherEloWon', 'lastTieScore', 'mapName'])
        writer.writeheader()
        for m in summary_stats:
            i += 1
            writer.writerow(m)
    print('done! rows written:', i)