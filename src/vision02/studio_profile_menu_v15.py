#!/usr/bin/env python3
"""Menu de perfis integrado ao Vision 02 Studio (geração e backup XDG).

Mantém compatibilidade com o instalador independente v1.0; jamais abre HID.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata

import yaml
from PIL import Image, ImageDraw, ImageFont

MENU = 'Menu de Perfis'
PAGE_SIZE = 14
MAX_PROFILES = 64


def config_root() -> Path:
    return Path(os.getenv('XDG_CONFIG_HOME') or (Path.home() / '.config')).expanduser() / 'vision02'


def state_root() -> Path:
    return Path(os.getenv('XDG_STATE_HOME') or (Path.home() / '.local/state')).expanduser() / 'vision02'


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f'Symlink não permitido: {path}')
    fd, name = tempfile.mkstemp(prefix='.vision02-menu-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _font(size: int, bold: bool = True):
    fname = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    try:
        return ImageFont.truetype(fname, size)
    except OSError:
        return ImageFont.load_default()


def short_name(name: str) -> str:
    flat = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', flat).strip().upper()[:13] or 'PERFIL'


def icon_png(name: str, index: int, *, kind: str = 'profile') -> bytes:
    palette = ['#143655', '#134536', '#5D3154', '#513F22', '#203E60', '#4A274B', '#204A4D', '#5B2F35']
    background = palette[index % len(palette)] if kind == 'profile' else '#192431'
    accent = ['#66D9FF', '#6BFFC0', '#FFA3E5', '#FFD27D', '#9DBFFF', '#D2A7FF', '#6DEAE9', '#FF9999'][index % 8] if kind == 'profile' else '#FFE08A'
    im = Image.new('RGB', (100, 100), '#080D17')
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 2, 97, 97), radius=16, fill=background, outline=accent, width=2)
    d.rounded_rectangle((9, 9, 90, 73), radius=12, fill='#0A1223')
    if kind == 'menu':
        for row in range(2):
            for col in range(2):
                x, y = 22 + col*27, 19+row*27
                d.rounded_rectangle((x,y,x+19,y+19),radius=4,outline=accent,width=3)
    elif kind == 'next':
        d.line([(31,29),(58,41),(31,53)],fill=accent,width=7,joint='curve')
        d.polygon([(56,23),(79,42),(56,61)],fill=accent)
    else:
        text = ''.join(word[0] for word in short_name(name).split()[:3]) or short_name(name)[:2]
        text=text[:3]
        font = _font(34 if len(text)<=2 else 27)
        bounds=d.textbbox((0,0),text,font=font)
        x=(100-(bounds[2]-bounds[0]))//2
        y=35-(bounds[3]-bounds[1])//2-bounds[1]
        d.text((x,y),text,font=font,fill=accent)
    d.rounded_rectangle((5,77,95,95),radius=6,fill='#020611')
    title = short_name(name)
    font = _font(9 if len(title)>10 else 10)
    bb=d.textbbox((0,0),title,font=font)
    d.text(((100-(bb[2]-bb[0]))//2, 81), title, font=font, fill='#FFFFFF')
    out=io.BytesIO();im.save(out,format='PNG',optimize=True)
    return out.getvalue()


def _profile_records(directory: Path) -> list[tuple[Path, dict, str]]:
    paths = sorted(directory.glob('*.yaml')) if directory.exists() else []
    if len(paths)>MAX_PROFILES:
        raise ValueError('Limite de 64 perfis excedido')
    found=[]; used=set()
    for p in paths:
        if p.is_symlink() or not p.is_file():
            raise ValueError(f'YAML não regular: {p}')
        text=p.read_text(encoding='utf-8')
        data=yaml.safe_load(text)
        if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('keys'),dict):
            raise ValueError(f'Perfil YAML inválido: {p.name}')
        name=data.get('name')
        if not isinstance(name,str) or not name.strip() or name in used:
            raise ValueError(f'Nome duplicado/inválido em {p.name}: {name!r}')
        used.add(name)
        found.append((p,data,text))
    return found


def is_menu_name(name: str) -> bool:
    return name == MENU or bool(re.fullmatch(re.escape(MENU)+r' [2-9][0-9]*',name))


def _entry15(item: dict) -> dict:
    return {'label': 'Menu de Perfis',
            'image': '../profile-icons/menu-de-perfis/voltar-menu.png',
            'action': {'type': 'profile', 'target': MENU},
            'appearance': {'background': '#192431', 'show_text': False}}


def _patch_15(text: str, entry: dict) -> str:
    """Substitui somente o bloco da tecla 15; conserva outros blocos e comentários."""
    node = yaml.compose(text)
    if not isinstance(node,yaml.MappingNode):
        raise ValueError('YAML raiz incompatível')
    keys_node = next((v for k,v in node.value if k.value=='keys'),None)
    if not isinstance(keys_node,yaml.MappingNode):
        raise ValueError('keys precisa ser um mapa YAML')
    key15 = next(((k,v) for k,v in keys_node.value if k.value=='15'),None)
    if key15 is not None:
        k, v=key15
        indent=k.start_mark.column
        start=text.rfind('\n',0,k.start_mark.index)+1
        end=v.end_mark.index
        # O próximo item pode começar com indentação antes do end_mark.
        after_line=text.rfind('\n',0,end)+1
        if after_line>=start and not text[after_line:end].strip():
            end=after_line
        chunk=yaml.safe_dump({15:entry},allow_unicode=True,sort_keys=False,width=100)
        replacement=''.join(' '*indent+line if line.strip() else line for line in chunk.splitlines(keepends=True))
        updated=text[:start]+replacement+text[end:]
    elif not keys_node.value:
        start=keys_node.start_mark.index;end=keys_node.end_mark.index
        if text[start:end].strip()!='{}':
            raise ValueError('keys vazio usa formato não suportado')
        updated=text[:start]+'\n'+''.join('  '+line for line in yaml.safe_dump({15:entry},allow_unicode=True,sort_keys=False).splitlines(keepends=True))+text[end:]
    else:
        last_k,last_v=keys_node.value[-1]
        if not isinstance(last_k,yaml.ScalarNode):
            raise ValueError('ID de tecla inválido')
        indent=last_k.start_mark.column
        end=keys_node.end_mark.index
        chunk=yaml.safe_dump({15:entry},allow_unicode=True,sort_keys=False,width=100)
        replacement=''.join(' '*indent+line for line in chunk.splitlines(keepends=True))
        prefix='' if end==0 or text[end-1]=='\n' else '\n'
        updated=text[:end]+prefix+replacement+text[end:]
    # As outras teclas devem permanecer semanticamente idênticas.
    old=yaml.safe_load(text); new=yaml.safe_load(updated)
    other={k:v for k,v in old.items() if k!='keys'}
    if other!={k:v for k,v in new.items() if k!='keys'}:
        raise AssertionError('Dados não relacionados foram alterados')
    for k,v in old['keys'].items():
        if k != 15 and new['keys'].get(k)!=v:
            raise AssertionError(f'Tecla {k} foi alterada')
    if new['keys'][15] != entry:
        raise AssertionError('Tecla 15 não foi aplicada')
    return updated


def _menu_doc(name: str, page: int, all_profiles: list[str], pages: int) -> dict:
    chunk=all_profiles[PAGE_SIZE*page:PAGE_SIZE*(page+1)]
    keys={}
    for i,target in enumerate(chunk,1):
        keys[i]={'label':target, 'image':f'../profile-icons/menu-de-perfis/perfil-{PAGE_SIZE*page+i:02}.png',
                 'action':{'type':'profile','target':target},
                 'appearance':{'background':'#11192B','show_text':False}}
    if pages>1:
        next_p=(page+1)%pages
        next_target=MENU if next_p==0 else f'{MENU} {next_p+1}'
        keys[15]={'label':'Próxima página' if next_p else 'Início do menu',
                  'image':'../profile-icons/menu-de-perfis/paginar.png',
                  'action':{'type':'profile','target':next_target},
                  'appearance':{'background':'#192431','show_text':False}}
    else:
        keys[15]={'label':'Menu de Perfis',
                  'image':'../profile-icons/menu-de-perfis/voltar-menu.png',
                  'action':{'type':'profile','target':MENU},
                  'appearance':{'background':'#192431','show_text':False}}
    return {'version':1,'name':name,'keys':keys}


def catalog_revision(directory: Path) -> str:
    """Revisão do catálogo consultado, independente de ordem e de mtime."""
    digest = hashlib.sha256()
    for path in sorted(directory.glob('*.yaml')):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Perfil YAML inválido: {path}')
        name = path.name.encode('utf-8')
        data = path.read_bytes()
        digest.update(len(name).to_bytes(4, 'big'))
        digest.update(name)
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)
    return digest.hexdigest()


def build_plan() -> dict:
    root=config_root();dirpath=root/'profiles'
    for parent in (root, root/'profile-icons', root/'profile-icons'/'menu-de-perfis'):
        if parent.is_symlink():
            raise ValueError(f'Diretório simbólico não permitido: {parent}')
    entries=_profile_records(dirpath)
    installed={data['name']:(p,data,text) for p,data,text in entries}
    if not entries:
        raise ValueError(f'Não há perfis instalados em {dirpath}')
    names=sorted((name for name in installed if not is_menu_name(name)),key=str.casefold)
    if not names:
        raise ValueError('Não há perfis para incluir no menu')
    pagecount=(len(names)+PAGE_SIZE-1)//PAGE_SIZE
    page_names=[MENU if i==0 else f'{MENU} {i+1}' for i in range(pagecount)]
    if len(entries)+len([n for n in page_names if n not in installed])>MAX_PROFILES:
        raise ValueError('Menu excederia o limite de 64 perfis; remova perfis antes de prosseguir')
    for name in page_names:
        if name in installed:
            p=installed[name][0]
            expected='menu-de-perfis.yaml' if name==MENU else f'menu-de-perfis-{page_names.index(name)+1}.yaml'
            if p.name!=expected:
                raise ValueError(f'Menu com nome reservado em arquivo inesperado: {p}')
    changes={}
    changed_names=[]
    previews=[]
    for name in names:
        path,doc,text=installed[name]
        old_15=doc['keys'].get(15)
        preview_label=old_15.get('label','sem rótulo') if isinstance(old_15,dict) else 'vazia'
        edited=_patch_15(text,_entry15(doc))
        raw=edited.encode('utf-8')
        if raw != text.encode('utf-8'):
            changes[path]=raw;changed_names.append(name)
        previews.append({'name':name,'key15_before':preview_label})
    icon_dir=root/'profile-icons'/'menu-de-perfis'
    for index,name in enumerate(names,1):
        changes[icon_dir/f'perfil-{index:02}.png']=icon_png(name,index)
    changes[icon_dir/'voltar-menu.png']=icon_png('MENU',0,kind='menu')
    changes[icon_dir/'paginar.png']=icon_png('PRÓXIMA',0,kind='next')
    for page,name in enumerate(page_names):
        filename='menu-de-perfis.yaml' if page==0 else f'menu-de-perfis-{page+1}.yaml'
        file=dirpath/filename
        document=_menu_doc(name,page,names,pagecount)
        changes[file]=yaml.safe_dump(document,allow_unicode=True,sort_keys=False,width=100).encode('utf-8')
    # Arquivos de páginas antigas não devem ficar com destinos obsoletos.
    stale=[p for p,data,_ in entries if is_menu_name(data['name']) and data['name'] not in page_names]
    if stale:
        raise ValueError('Existem páginas antigas do menu; faça backup e remova-as antes de regenerar: '+', '.join(p.name for p in stale))
    # Não regravar conteúdo idêntico e proteger caminhos.
    changes={path:raw for path,raw in changes.items() if not path.exists() or path.read_bytes()!=raw}
    for path in changes:
        if path.is_symlink():raise ValueError(f'Caminho simbólico bloqueado: {path}')
    current_hash={str(path.relative_to(root)):hash_bytes(path.read_bytes()) if path.exists() else None for path in changes}
    return {'root':root, 'names':names,'pages':page_names,'changes':changes,'hashes':current_hash,
            'revision':catalog_revision(dirpath),
            'changed_profiles':changed_names,'preview':previews}


def plan_result(plan: dict) -> dict:
    return {'ok':True,'count':len(plan['names']),'pages':plan['pages'],
            'revision':plan['revision'],
            'profiles':plan['preview'],'updated_profiles':plan['changed_profiles'],
            'files_to_write':len(plan['changes']),
            'message':'A tecla 15 dos perfis existentes será substituída por Voltar ao Menu; demais teclas preservadas.'}


@contextmanager
def _catalog_lock(root: Path):
    p=root/'profiles';p.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.is_symlink():raise ValueError('Pasta de perfis simbólica não permitida')
    fd=os.open(p/'.catalog.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)


def _validate_candidates(changes: dict, root: Path, project: Path) -> None:
    # O loader do projeto exige que caminhos de imagens sejam válidos relativos ao YAML.
    if not (project/'src/vision02/profiles/loader.py').is_file():
        raise ValueError('Projeto Rise Mode Vision02 inválido')
    sys.path.insert(0,str(project/'src'))
    from vision02.profiles import ProfileManager,validate_profile_targets,load_profile
    from vision02.rendering import render_key
    entries=sorted((root/'profiles').glob('*.yaml'))
    virtual_files={p for p in changes if p.suffix=='.yaml'}
    all_paths=sorted(set(entries)|virtual_files)
    staged=[]
    manager=ProfileManager()
    try:
        for p in all_paths:
            data=changes.get(p)
            if data is None:
                manager.register(load_profile(p));continue
            fd,name=tempfile.mkstemp(prefix='.menu-validate-',suffix='.yaml',dir=p.parent)
            staging=Path(name);staged.append(staging)
            with os.fdopen(fd,'wb') as w:w.write(data)
            manager.register(load_profile(staging))
        validate_profile_targets(manager)
        # Teste real de renderização de um item da página principal.
        profile=manager.get(MENU)
        for key in profile.keys.values():
            result=render_key(key)
            if hasattr(result,'size') and result.size!=(100,100):
                raise ValueError('Imagem de tecla inválida')
    finally:
        for p in staged:p.unlink(missing_ok=True)


def _verify_changes(plan: dict):
    for rel,expected in plan['hashes'].items():
        p=plan['root']/rel
        actual=hash_bytes(p.read_bytes()) if p.exists() else None
        if actual!=expected:
            raise RuntimeError(f'Arquivo alterado desde a inspeção: {rel}')


def _rollback(manifest:dict, backup:Path, root:Path, *, verify:bool=True):
    # A restauração exige que nenhum arquivo tenha sido modificado desde a aplicação.
    for info in manifest['files']:
        path=root/info['path']
        current=hash_bytes(path.read_bytes()) if path.exists() else None
        if verify and current!=info['installed_sha256']:
            raise RuntimeError(f'Restauração bloqueada por alteração local: {path}')
    for info in reversed(manifest['files']):
        path=root/info['path']
        if info['original_sha256'] is None:
            path.unlink(missing_ok=True)
        else:
            data=(backup/'originals'/info['path']).read_bytes()
            if hash_bytes(data)!=info['original_sha256']:
                raise RuntimeError('Arquivo do backup corrompido')
            _atomic(path,data)
    return len(manifest['files'])


def apply(project: Path, *, expected_revision: str | None = None) -> dict:
    root=config_root()
    with _catalog_lock(root):
        plan=build_plan()
        if expected_revision is not None and plan['revision'] != expected_revision:
            raise RuntimeError('Perfis alterados após a inspeção; inspecione novamente antes de instalar.')
        _verify_changes(plan)
        changes=plan['changes']
        if not changes:return {'ok':True,'message':'Menu já está sincronizado','files':0}
        backup=state_root()/'menu-perfis-backups'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+os.urandom(4).hex())
        backup.mkdir(parents=True,exist_ok=False,mode=0o700)
        manifest={'version':1,'files':[],'project':str(project)}
        try:
            for p,content in changes.items():
                if p.exists() and p.is_symlink():raise ValueError(f'Symlink detectado: {p}')
                relative=str(p.relative_to(root))
                original=p.read_bytes() if p.exists() else None
                info={'path':relative,'original_sha256':hash_bytes(original) if original is not None else None,'installed_sha256':hash_bytes(content)}
                manifest['files'].append(info)
                if original is not None:
                    dest=backup/'originals'/relative
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(original);dest.chmod(0o600)
            # Imagens precisam existir antes da validação dos YAML.
            for p,data in changes.items():
                if p.suffix=='.png':_atomic(p,data)
            _validate_candidates(changes,root,project)
            for p,data in changes.items():
                if p.suffix=='.yaml':_atomic(p,data)
            # Conferir catálogo real já instalado.
            _validate_candidates({},root,project)
            (backup/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            return {'ok':True,'backup':str(backup),'files':len(changes),'profiles':plan['names'],
                    'pages':plan['pages'],'message':'Perfis e menu configurados. Recarregue o catálogo no Studio.'}
        except Exception:
            # Mesmo com falha durante gravação, restaurar apenas o que efetivamente foi escrito.
            _rollback(manifest,backup,root,verify=False)
            raise


def restore(backup:Path)->dict:
    manifest_path=backup/'manifest.json'
    if not manifest_path.is_file():raise ValueError('Backup sem manifesto: '+str(backup))
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    root=config_root()
    with _catalog_lock(root):
        count=_rollback(manifest,backup,root,verify=True)
    return {'ok':True,'files':count,'message':'Backup restaurado. Recarregue o catálogo.'}


def latest_backup()->Path|None:
    root=state_root()/'menu-perfis-backups'
    files=sorted(root.glob('*/manifest.json'),reverse=True) if root.exists() else []
    return files[0].parent if files else None


def reload(project:Path, *, open_menu:bool=False)->dict:
    if not (project/'src/vision02/control_ipc.py').is_file():raise ValueError('Projeto inválido')
    sys.path.insert(0,str(project/'src'))
    from vision02.control_ipc import request
    result=request('switch',target=MENU,timeout=30) if open_menu else request('reload',timeout=30)
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description='Cria perfil de menu de navegação e atalhos de retorno')
    ap.add_argument('--project',type=Path,default=Path.home()/'projetos/rise-mode-vision02/rise-mode-vision02-linux')
    ap.add_argument('--expected-revision',default=None,help='SHA-256 do catálogo inspecionado')
    commands=ap.add_mutually_exclusive_group(required=True)
    commands.add_argument('--plan',action='store_true')
    commands.add_argument('--apply',action='store_true')
    commands.add_argument('--reload',action='store_true')
    commands.add_argument('--open-menu',action='store_true')
    commands.add_argument('--restore',type=Path)
    args=ap.parse_args(argv)
    try:
        if args.plan:result=plan_result(build_plan())
        elif args.apply:result=apply(args.project.resolve(),expected_revision=args.expected_revision)
        elif args.reload:result=reload(args.project.resolve())
        elif args.open_menu:result=reload(args.project.resolve(),open_menu=True)
        else:result=restore(args.restore.resolve())
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result.get('ok',False) else 2
    except (OSError,RuntimeError,ValueError,KeyError,TypeError,ImportError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False))
        return 2


if __name__=='__main__':raise SystemExit(main())
