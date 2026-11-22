#!/usr/bin/python3
"""Parse a .torrent or fetch only magnet metadata. No payload piece requests."""
import base64
import json
import sys
import tempfile
import time
import libtorrent as lt

def preview(request):
    if request.get('magnet'):
        magnet = request['magnet']
        if not isinstance(magnet,str) or not magnet.startswith('magnet:?') or len(magnet)>16384:
            raise ValueError('Некорректная magnet-ссылка')
        with tempfile.TemporaryDirectory(prefix='harbor-metadata-') as directory:
            session = lt.session({'listen_interfaces':'0.0.0.0:0', 'enable_upnp':False,
                                  'enable_natpmp':False, 'enable_lsd':False})
            params = lt.parse_magnet_uri(magnet)
            params.save_path = directory
            # upload_mode forbids requesting file pieces, but permits ut_metadata exchange.
            params.flags |= lt.torrent_flags.upload_mode
            params.flags &= ~lt.torrent_flags.auto_managed
            params.flags &= ~lt.torrent_flags.paused
            handle = session.add_torrent(params)
            deadline = time.monotonic() + 90
            while not handle.has_metadata():
                if time.monotonic() > deadline:
                    raise ValueError('Не удалось получить метаданные за 90 секунд. Проверьте доступность пиров или загрузите .torrent-файл.')
                status = handle.status()
                if status.errc.value(): raise ValueError(status.errc.message())
                time.sleep(0.2)
            handle.pause()
            info = handle.torrent_file()
            generated = lt.create_torrent(info)
            # Keep trackers from the magnet URI for the Transmission instance.
            for tracker in handle.trackers(): generated.add_tracker(tracker['url'], tracker.get('tier',0))
            raw = lt.bencode(generated.generate())
            payload = handle.status().total_payload_download
            session.remove_torrent(handle)
            if payload != 0: raise RuntimeError('Metadata resolver unexpectedly received payload')
    else:
        raw = base64.b64decode(request.get('metainfo',''), validate=True)
        if not 0 < len(raw) <= 5*1024*1024: raise ValueError('Размер .torrent должен быть до 5 МиБ')
        info = lt.torrent_info(lt.bdecode(raw))
    files = info.files()
    if not 0 < files.num_files() <= 20000: raise ValueError('Поддерживается от 1 до 20000 файлов')
    return {'name':info.name(), 'files':[{'name':files.file_path(i),'length':files.file_size(i)} for i in range(files.num_files())],
            'metainfo':base64.b64encode(raw).decode()}

if __name__ == '__main__':
    try:
        result = preview(json.load(sys.stdin)); print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'error':str(exc)})); sys.exit(1)
