import os
import json
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------- CONFIGURAÇÃO DA APLICAÇÃO ----------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta-projeto-carajas'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///carajas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

CHAVE_VALOR_AUXILIO = 'valor_auxilio_deslocamento'
VALOR_AUXILIO_PADRAO = 50.0

AREAS_PADRAO = {
    'Capital / Região Metropolitana': {'Cheia': 250.0, 'Meia': 125.0},
    'Interior do Estado': {'Cheia': 180.0, 'Meia': 90.0},
    'Outros Estados': {'Cheia': 320.0, 'Meia': 160.0}
}

# ---------------- MODELOS DO BANCO DE DADOS ----------------
class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    is_organizador = db.Column(db.Boolean, default=False)
    is_aprovador = db.Column(db.Boolean, default=False)
    perfil = db.Column(db.String(50), default='comum')

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def checar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class Coordenacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)


class TipoServicoExterno(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=True)


class TipoLocacaoVeiculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)


class AreaDiaria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)


class ValorDiaria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey('area_diaria.id'), nullable=False)
    tipo_diaria = db.Column(db.String(20), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)


class Configuracao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.String(255), nullable=False)


class Solicitacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    ponto_focal = db.Column(db.String(100))
    atividade_projeto = db.Column(db.String(200))
    valor_total = db.Column(db.Numeric(10, 2), default=0.0)
    coordenacao_solicitante_id = db.Column(db.Integer, db.ForeignKey('coordenacao.id'))
    contato_solicitante = db.Column(db.String(100))
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)


class PrestadorServico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacao.id'), nullable=False)
    tipo_prestador = db.Column(db.String(10))
    categoria_servico = db.Column(db.String(100))
    nome_servico = db.Column(db.String(150))
    fornecedor_sugerido = db.Column(db.String(150))
    especificacao = db.Column(db.Text)
    justificativa = db.Column(db.Text)
    valor_servico = db.Column(db.Numeric(10, 2))
    nome_empresa = db.Column(db.String(150))
    cnpj = db.Column(db.String(20))
    nome_prestador = db.Column(db.String(150))
    cpf_prestador = db.Column(db.String(20))
    rg_prestador = db.Column(db.String(20))
    telefone_prestador = db.Column(db.String(30))
    pis_nis = db.Column(db.String(30))
    endereco_prestador = db.Column(db.String(255))
    banco = db.Column(db.String(50))
    agencia = db.Column(db.String(20))
    conta = db.Column(db.String(20))
    chave_pix = db.Column(db.String(100))


class Anexo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacao.id'), nullable=False)
    nome_arquivo = db.Column(db.String(255), nullable=False)
    tipo_conteudo = db.Column(db.String(100))
    dados = db.Column(db.LargeBinary)


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))


# ---------------- UTILS & HELPER FUNCTIONS ----------------
def somente_organizador():
    if not current_user.is_authenticated or not current_user.is_organizador:
        flash('Acesso restrito apenas a organizadores.')
        return redirect(url_for('inicio'))


def obter_configuracao(chave, padrao):
    cfg = Configuracao.query.filter_by(chave=chave).first()
    return cfg.valor if cfg else padrao


def montar_opcoes_coordenacoes():
    coords = Coordenacao.query.order_by(Coordenacao.nome).all()
    return ''.join([f'<option value="{c.id}">{c.nome}</option>' for c in coords])


def montar_opcoes_tipos_servico():
    tipos = TipoServicoExterno.query.order_by(TipoServicoExterno.nome).all()
    return ''.join([f'<option value="{t.nome}">{t.nome}</option>' for t in tipos])


def montar_dict_valores_servico():
    tipos = TipoServicoExterno.query.all()
    valores = {t.nome: float(t.valor) if t.valor else 0 for t in tipos}
    return json.dumps(valores)


def render_pagina(titulo, conteudo):
    base_html = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>{titulo} - Sistema Carajás</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f4f6f9; color: #333; }}
            .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #2b5876; color: white; }}
            .btn {{ padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
            .btn-salvar {{ background-color: #28a745; color: white; }}
            .btn-excluir {{ background-color: #dc3545; color: white; }}
            .btn-adicionar {{ background-color: #007bff; color: white; }}
            .bloco {{ background: #f8f9fa; border: 1px solid #e9ecef; padding: 15px; margin-top: 15px; border-radius: 4px; }}
            .flash {{ padding: 10px; margin-bottom: 15px; border-radius: 4px; }}
            .flash-sucesso {{ background: #d4edda; color: #155724; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{titulo}</h1>
            <hr>
            {conteudo}
        </div>
    </body>
    </html>
    """
    return render_template_string(base_html)


# ---------------- ROTAS GERAIS & LOCAÇÃO ----------------
@app.route('/')
def inicio():
    return render_pagina('Início', '<h2>Bem-vindo ao Sistema de Gestão e Solicitações</h2>')


@app.route('/cadastros/locacao-veiculo')
@login_required
def cadastro_locacao_veiculo():
    somente_organizador()
    tipos = TipoLocacaoVeiculo.query.order_by(TipoLocacaoVeiculo.nome).all()
    linhas_html = ''
    for tipo in tipos:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_locacao_veiculo_atualizar', tipo_id=tipo.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{tipo.nome}" style="width:250px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_locacao_veiculo_excluir', tipo_id=tipo.id)}" style="display:inline;" onsubmit="return confirm('Excluir este tipo?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """
    conteudo = f"""
    <h2>Tipos de Locação de Veículo</h2>
    <table>
        <tr><th>Nome</th><th>Ações</th></tr>
        {linhas_html}
    </table>
    <h3 style="margin-top:25px;">Adicionar novo tipo</h3>
    <form method="POST" action="{url_for('cadastro_locacao_veiculo_adicionar')}" style="max-width:400px;">
        <label>Nome do tipo:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>
        <button type="submit" class="btn btn-adicionar">Adicionar tipo</button>
    </form>
    """
    return render_pagina('Cadastro de Locação de Veículos', conteudo)


@app.route('/cadastros/locacao-veiculo/adicionar', methods=['POST'])
@login_required
def cadastro_locacao_veiculo_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    if nome and not TipoLocacaoVeiculo.query.filter_by(nome=nome).first():
        db.session.add(TipoLocacaoVeiculo(nome=nome))
        db.session.commit()
        flash(f'Tipo "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


@app.route('/cadastros/locacao-veiculo/<int:tipo_id>/atualizar', methods=['POST'])
@login_required
def cadastro_locacao_veiculo_atualizar(tipo_id):
    somente_organizador()
    tipo = TipoLocacaoVeiculo.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    db.session.commit()
    flash('Tipo atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


@app.route('/cadastros/locacao-veiculo/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_locacao_veiculo_excluir(tipo_id):
    somente_organizador()
    tipo = TipoLocacaoVeiculo.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Tipo "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


# ---------------- SOLICITAÇÃO: SERVIÇOS EXTERNOS ----------------
SERVICO_EXTERNO_FORM_TEMPLATE = """
<form method="POST" enctype="multipart/form-data" style="max-width: 600px;" id="form-servico-externo">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <h3>Dados do Prestador</h3>
    <label>Tipo de Prestador: <span style="color:red;">*</span></label><br>
    <select name="tipo_prestador" id="tipo_prestador" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        <option value="PJ">Pessoa Jurídica (PJ)</option>
        <option value="PF">Pessoa Física (PF)</option>
    </select><br>

    <label>Categoria do Serviço: <span style="color:red;">*</span></label><br>
    <select name="categoria_servico" id="categoria_servico" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_TIPOS_SERVICO__
    </select><br>

    <label>Nome do Serviço: <span style="color:red;">*</span></label><br>
    <input type="text" name="nome_servico" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Fornecedor Sugerido:</label><br>
    <input type="text" name="fornecedor_sugerido" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Especificação Detalhada: <span style="color:red;">*</span></label><br>
    <textarea name="especificacao" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Justificativa da Solicitação: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Valor do Serviço (R$): <span style="color:red;">*</span></label><br>
    <input type="text" id="valor_servico_display" placeholder="R$ 0,00" required style="padding:6px; margin-bottom:10px; width:150px;">
    <input type="hidden" name="valor_servico" id="valor_servico_hidden"><br>

    <div id="bloco_pj" style="display:none;" class="bloco">
        <h4>Dados da Empresa (PJ)</h4>
        <label>Razão Social / Nome da Empresa:</label><br>
        <input type="text" name="nome_empresa" id="nome_empresa" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>CNPJ:</label><br>
        <input type="text" name="cnpj" id="cnpj" style="padding:6px; margin-bottom:10px;"><br>
    </div>

    <div id="bloco_pf" style="display:none;" class="bloco">
        <h4>Dados do Prestador (PF)</h4>
        <label>Nome Completo:</label><br>
        <input type="text" name="nome_prestador" id="nome_prestador" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>CPF:</label><br>
        <input type="text" name="cpf_prestador" id="cpf_prestador" style="padding:6px; margin-bottom:10px;"><br>

        <label>RG / Órgão Expedidor:</label><br>
        <input type="text" name="rg_prestador" id="rg_prestador" style="padding:6px; margin-bottom:10px;"><br>

        <label>Telefone:</label><br>
        <input type="text" name="telefone_prestador" id="telefone_prestador" style="padding:6px; margin-bottom:10px;"><br>

        <label>PIS/NIS:</label><br>
        <input type="text" name="pis_nis" id="pis_nis" style="padding:6px; margin-bottom:10px;"><br>

        <label>Endereço Completo:</label><br>
        <input type="text" name="endereco_prestador" id="endereco_prestador" style="width:100%; padding:6px; margin-bottom:10px;"><br>
    </div>

    <div class="bloco">
        <h4>Dados Bancários para Pagamento</h4>
        <label>Banco:</label><br>
        <input type="text" name="banco" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Agência:</label><br>
        <input type="text" name="agencia" style="padding:6px; margin-bottom:10px; width:150px;"><br>

        <label>Conta Corrente:</label><br>
        <input type="text" name="conta" style="padding:6px; margin-bottom:10px; width:200px;"><br>

        <label>Chave PIX:</label><br>
        <input type="text" name="chave_pix" style="width:100%; padding:6px; margin-bottom:10px;"><br>
    </div>

    <label>Anexar Proposta / Orçamentos / Documentos:</label><br>
    <input type="file" name="anexos" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx" style="margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
var VALORES_SERVICO = __VALORES_SERVICO__;

document.getElementById('tipo_prestador').addEventListener('change', function() {
    var blocoPJ = document.getElementById('bloco_pj');
    var blocoPF = document.getElementById('bloco_pf');

    if (this.value === 'PJ') {
        blocoPJ.style.display = 'block';
        blocoPF.style.display = 'none';
    } else if (this.value === 'PF') {
        blocoPJ.style.display = 'none';
        blocoPF.style.display = 'block';
    } else {
        blocoPJ.style.display = 'none';
        blocoPF.style.display = 'none';
    }
});

var campoValor = document.getElementById('valor_servico_display');
var campoValorOculto = document.getElementById('valor_servico_hidden');

campoValor.addEventListener('input', function() {
    var somenteDigitos = campoValor.value.replace(/\D/g, '');
    if (somenteDigitos === '') {
        campoValor.value = '';
        campoValorOculto.value = '';
        return;
    }
    var valorCentavos = parseInt(somenteDigitos, 10);
    var valorReais = valorCentavos / 100;

    campoValorOculto.value = valorReais.toFixed(2);
    campoValor.value = 'R$ ' + valorReais.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
});
</script>
"""


@app.route('/solicitacao/servico-externo', methods=['GET', 'POST'])
@login_required
def servico_externo_form():
    if request.method == 'POST':
        valor_servico = float(request.form.get('valor_servico') or 0)

        solicitacao = Solicitacao(
            tipo='servico_externo',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_servico,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        prestador = PrestadorServico(
            solicitacao_id=solicitacao.id,
            tipo_prestador=request.form.get('tipo_prestador'),
            categoria_servico=request.form.get('categoria_servico'),
            nome_servico=request.form.get('nome_servico'),
            fornecedor_sugerido=request.form.get('fornecedor_sugerido'),
            especificacao=request.form.get('especificacao'),
            justificativa=request.form.get('justificativa'),
            valor_servico=valor_servico,
            nome_empresa=request.form.get('nome_empresa'),
            cnpj=request.form.get('cnpj'),
            nome_prestador=request.form.get('nome_prestador'),
            cpf_prestador=request.form.get('cpf_prestador'),
            rg_prestador=request.form.get('rg_prestador'),
            telefone_prestador=request.form.get('telefone_prestador'),
            pis_nis=request.form.get('pis_nis'),
            endereco_prestador=request.form.get('endereco_prestador'),
            banco=request.form.get('banco'),
            agencia=request.form.get('agencia'),
            conta=request.form.get('conta'),
            chave_pix=request.form.get('chave_pix'),
        )
        db.session.add(prestador)

        arquivos = request.files.getlist('anexos')
        for arquivo in arquivos:
            if arquivo and arquivo.filename:
                db.session.add(Anexo(
                    solicitacao_id=solicitacao.id,
                    nome_arquivo=arquivo.filename,
                    tipo_conteudo=arquivo.content_type,
                    dados=arquivo.read(),
                ))

        db.session.commit()
        flash('Solicitação de serviço externo enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = SERVICO_EXTERNO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__OPCOES_TIPOS_SERVICO__', montar_opcoes_tipos_servico())
    form_html = form_html.replace('__VALORES_SERVICO__', montar_dict_valores_servico())
    return render_pagina('Solicitação de Serviços Externos', form_html)


# ---------------- CADASTROS: SERVIÇOS EXTERNOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/servico-externo')
@login_required
def cadastro_servico_externo():
    somente_organizador()

    tipos = TipoServicoExterno.query.order_by(TipoServicoExterno.nome).all()
    linhas_html = ''
    for tipo in tipos:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_servico_externo_atualizar', tipo_id=tipo.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{tipo.nome}" style="width:200px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor" value="{tipo.valor}" style="width:100px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_servico_externo_excluir', tipo_id=tipo.id)}" style="display:inline;" onsubmit="return confirm('Excluir o serviço {tipo.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Tipos de Serviço Externo</h2>
    <table>
        <tr><th>Nome</th><th>Valor Referência (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar novo serviço</h3>
    <form method="POST" action="{url_for('cadastro_servico_externo_adicionar')}" style="max-width:400px;">
        <label>Nome do serviço:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor referência (R$):</label><br>
        <input type="number" step="0.01" name="valor" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar serviço</button>
    </form>
    """
    return render_pagina('Cadastro de Serviços Externos', conteudo)


@app.route('/cadastros/servico-externo/adicionar', methods=['POST'])
@login_required
def cadastro_servico_externo_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    valor = request.form.get('valor')

    if not nome:
        flash('Informe o nome do serviço.')
        return redirect(url_for('cadastro_servico_externo'))

    if TipoServicoExterno.query.filter_by(nome=nome).first():
        flash('Já existe um serviço com esse nome.')
        return redirect(url_for('cadastro_servico_externo'))

    db.session.add(TipoServicoExterno(nome=nome, valor=valor))
    db.session.commit()
    flash(f'Serviço "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/atualizar', methods=['POST'])
@login_required
def cadastro_servico_externo_atualizar(tipo_id):
    somente_organizador()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor = request.form.get('valor')
    db.session.commit()
    flash('Serviço externo atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_servico_externo_excluir(tipo_id):
    somente_organizador()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Serviço "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


# ---------------- CADASTROS: DIÁRIAS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/diaria')
@login_required
def cadastro_diaria():
    somente_organizador()

    areas = AreaDiaria.query.order_by(AreaDiaria.nome).all()
    auxilio_atual = obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)

    linhas_html = ''
    for area in areas:
        v_cheia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Cheia').first()
        v_meia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Meia').first()

        val_cheia = float(v_cheia.valor) if v_cheia else 0
        val_meia = float(v_meia.valor) if v_meia else 0

        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_diaria_atualizar', area_id=area.id)}" style="display:contents;">
            <td><input type="text" name="nome_area" value="{area.nome}" style="width:150px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_cheia" value="{val_cheia}" style="width:90px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_meia" value="{val_meia}" style="width:90px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_diaria_excluir', area_id=area.id)}" style="display:inline;" onsubmit="return confirm('Excluir a área {area.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Valores de Diárias por Área</h2>
    <table>
        <tr><th>Área / Região</th><th>Valor Cheia (R$)</th><th>Valor Meia (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova área</h3>
    <form method="POST" action="{url_for('cadastro_diaria_adicionar')}" style="max-width:400px; margin-bottom:30px;">
        <label>Nome da área:</label><br>
        <input type="text" name="nome_area" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor Diária Cheia (R$):</label><br>
        <input type="number" step="0.01" name="valor_cheia" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Valor Diária Meia (R$):</label><br>
        <input type="number" step="0.01" name="valor_meia" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar área</button>
    </form>

    <div class="bloco" style="max-width:400px;">
        <h3>Auxílio Deslocamento</h3>
        <form method="POST" action="{url_for('cadastro_diaria_auxilio')}">
            <label>Valor unitário do Auxílio Deslocamento (R$):</label><br>
            <input type="number" step="0.01" name="valor_auxilio" value="{auxilio_atual}" required style="padding:6px; width:150px; margin-bottom:10px;"><br>
            <button type="submit" class="btn btn-salvar">Atualizar Auxílio</button>
        </form>
    </div>
    """
    return render_pagina('Cadastro de Diárias', conteudo)


@app.route('/cadastros/diaria/adicionar', methods=['POST'])
@login_required
def cadastro_diaria_adicionar():
    somente_organizador()
    nome_area = request.form.get('nome_area', '').strip()
    valor_cheia = request.form.get('valor_cheia')
    valor_meia = request.form.get('valor_meia')

    if not nome_area:
        flash('Informe o nome da área.')
        return redirect(url_for('cadastro_diaria'))

    if AreaDiaria.query.filter_by(nome=nome_area).first():
        flash('Já existe uma área com esse nome.')
        return redirect(url_for('cadastro_diaria'))

    area = AreaDiaria(nome=nome_area)
    db.session.add(area)
    db.session.flush()

    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Cheia', valor=valor_cheia))
    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Meia', valor=valor_meia))

    db.session.commit()
    flash(f'Área "{nome_area}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/<int:area_id>/atualizar', methods=['POST'])
@login_required
def cadastro_diaria_atualizar(area_id):
    somente_organizador()
    area = AreaDiaria.query.get_or_404(area_id)
    area.nome = request.form.get('nome_area', '').strip()

    v_cheia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Cheia').first()
    if v_cheia:
        v_cheia.valor = request.form.get('valor_cheia')
    else:
        db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Cheia', valor=request.form.get('valor_cheia')))

    v_meia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Meia').first()
    if v_meia:
        v_meia.valor = request.form.get('valor_meia')
    else:
        db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Meia', valor=request.form.get('valor_meia')))

    db.session.commit()
    flash('Valores atualizados com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/<int:area_id>/excluir', methods=['POST'])
@login_required
def cadastro_diaria_excluir(area_id):
    somente_organizador()
    area = AreaDiaria.query.get_or_404(area_id)
    nome = area.nome
    db.session.delete(area)
    db.session.commit()
    flash(f'Área "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/auxilio', methods=['POST'])
@login_required
def cadastro_diaria_auxilio():
    somente_organizador()
    valor = request.form.get('valor_auxilio')

    config = Configuracao.query.filter_by(chave=CHAVE_VALOR_AUXILIO).first()
    if config:
        config.valor = valor
    else:
        db.session.add(Configuracao(chave=CHAVE_VALOR_AUXILIO, valor=valor))

    db.session.commit()
    flash('Valor do Auxílio Deslocamento atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


# ---------------- CADASTROS: COORDENAÇÕES (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/coordenacao')
@login_required
def cadastro_coordenacao():
    somente_organizador()

    coordenacoes = Coordenacao.query.order_by(Coordenacao.nome).all()
    linhas_html = ''
    for coord in coordenacoes:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_coordenacao_atualizar', coord_id=coord.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{coord.nome}" style="width:250px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_coordenacao_excluir', coord_id=coord.id)}" style="display:inline;" onsubmit="return confirm('Excluir a coordenação {coord.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Coordenações Solicitantes</h2>
    <table>
        <tr><th>Nome</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova coordenação</h3>
    <form method="POST" action="{url_for('cadastro_coordenacao_adicionar')}" style="max-width:400px;">
        <label>Nome da coordenação:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar coordenação</button>
    </form>
    """
    return render_pagina('Cadastro de Coordenação', conteudo)


@app.route('/cadastros/coordenacao/adicionar', methods=['POST'])
@login_required
def cadastro_coordenacao_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()

    if not nome:
        flash('Informe o nome da coordenação.')
        return redirect(url_for('cadastro_coordenacao'))

    if Coordenacao.query.filter_by(nome=nome).first():
        flash('Já existe uma coordenação com esse nome.')
        return redirect(url_for('cadastro_coordenacao'))

    db.session.add(Coordenacao(nome=nome))
    db.session.commit()
    flash(f'Coordenação "{nome}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coord_id>/atualizar', methods=['POST'])
@login_required
def cadastro_coordenacao_atualizar(coord_id):
    somente_organizador()
    coord = Coordenacao.query.get_or_404(coord_id)
    coord.nome = request.form.get('nome', '').strip()
    db.session.commit()
    flash('Coordenação atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coord_id>/excluir', methods=['POST'])
@login_required
def cadastro_coordenacao_excluir(coord_id):
    somente_organizador()
    coord = Coordenacao.query.get_or_404(coord_id)
    nome = coord.nome
    db.session.delete(coord)
    db.session.commit()
    flash(f'Coordenação "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


# ---------------- INICIALIZAÇÃO E SEED DO BANCO DE DADOS ----------------
def inicializar_banco():
    with app.app_context():
        db.create_all()

        # Seed do usuário administrador padrão
        if not Usuario.query.filter_by(email='admin@carajas.org').first():
            admin = Usuario(
                nome='Administrador',
                email='admin@carajas.org',
                is_organizador=True,
                is_aprovador=True,
                perfil='analista',
            )
            admin.set_senha('admin123')
            db.session.add(admin)

        # Seed das áreas e valores padrão de diária
        for area_nome, valores in AREAS_PADRAO.items():
            area = AreaDiaria.query.filter_by(nome=area_nome).first()
            if not area:
                area = AreaDiaria(nome=area_nome)
                db.session.add(area)
                db.session.flush()

                for tipo, valor in valores.items():
                    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria=tipo, valor=valor))

        # Seed da configuração padrão do auxílio deslocamento
        if not Configuracao.query.filter_by(chave=CHAVE_VALOR_AUXILIO).first():
            db.session.add(Configuracao(chave=CHAVE_VALOR_AUXILIO, valor=VALOR_AUXILIO_PADRAO))

        db.session.commit()


if __name__ == '__main__':
    inicializar_banco()
    app.run(debug=True)
    db.session.commit()
    flash(f'Tipo "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


# ---------------- SOLICITAÇÃO: SERVIÇOS EXTERNOS ----------------
SERVICO_EXTERNO_FORM_TEMPLATE = """
<form method="POST" enctype="multipart/form-data" style="max-width: 600px;" id="form-servico-externo">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <h3>Dados do Prestador</h3>
    <label>Tipo de Prestador: <span style="color:red;">*</span></label><br>
    <select name="tipo_prestador" id="tipo_prestador" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        <option value="PJ">Pessoa Jurídica (PJ)</option>
        <option value="PF">Pessoa Física (PF)</option>
    </select><br>

    <label>Categoria do Serviço: <span style="color:red;">*</span></label><br>
    <select name="categoria_servico" id="categoria_servico" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_TIPOS_SERVICO__
    </select><br>

    <label>Nome do Serviço: <span style="color:red;">*</span></label><br>
    <input type="text" name="nome_servico" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Fornecedor Sugerido:</label><br>
    <input type="text" name="fornecedor_sugerido" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Especificação Detalhada: <span style="color:red;">*</span></label><br>
    <textarea name="especificacao" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Justificativa da Solicitação: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Valor do Serviço (R$): <span style="color:red;">*</span></label><br>
    <input type="text" id="valor_servico_display" placeholder="R$ 0,00" required style="padding:6px; margin-bottom:10px; width:150px;">
    <input type="hidden" name="valor_servico" id="valor_servico_hidden"><br>

    <!-- Campos específicos para Pessoa Jurídica -->
    <div id="bloco_pj" style="display:none;" class="bloco">
        <h4>Dados da Empresa (PJ)</h4>
        <label>Razão Social / Nome da Empresa:</label><br>
        <input type="text" name="nome_empresa" id="nome_empresa" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>CNPJ:</label><br>
        <input type="text" name="cnpj" id="cnpj" style="padding:6px; margin-bottom:10px;"><br>
    </div>

    <!-- Campos específicos para Pessoa Física -->
    <div id="bloco_pf" style="display:none;" class="bloco">
        <h4>Dados do Prestador (PF)</h4>
        <label>Nome Completo:</label><br>
        <input type="text" name="nome_prestador" id="nome_prestador" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>CPF:</label><br>
        <input type="text" name="cpf_prestador" id="cpf_prestador" style="padding:6px; margin-bottom:10px;"><br>

        <label>RG / Órgão Expedidor:</label><br>
        <input type="text" name="rg_prestador" id="rg_prestador" style="padding:6px; margin-bottom:10px;"><br>

        <label>Telefone:</label><br>
        <input type="text" name="telefone_prestador" id="telefone_prestador" style="padding:6px; margin-bottom:10px;"><br>

        <label>PIS/NIS:</label><br>
        <input type="text" name="pis_nis" id="pis_nis" style="padding:6px; margin-bottom:10px;"><br>

        <label>Endereço Completo:</label><br>
        <input type="text" name="endereco_prestador" id="endereco_prestador" style="width:100%; padding:6px; margin-bottom:10px;"><br>
    </div>

    <div class="bloco">
        <h4>Dados Bancários para Pagamento</h4>
        <label>Banco:</label><br>
        <input type="text" name="banco" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Agência:</label><br>
        <input type="text" name="agencia" style="padding:6px; margin-bottom:10px; width:150px;"><br>

        <label>Conta Corrente:</label><br>
        <input type="text" name="conta" style="padding:6px; margin-bottom:10px; width:200px;"><br>

        <label>Chave PIX:</label><br>
        <input type="text" name="chave_pix" style="width:100%; padding:6px; margin-bottom:10px;"><br>
    </div>

    <label>Anexar Proposta / Orçamentos / Documentos:</label><br>
    <input type="file" name="anexos" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx" style="margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
var VALORES_SERVICO = __VALORES_SERVICO__;

document.getElementById('tipo_prestador').addEventListener('change', function() {
    var blocoPJ = document.getElementById('bloco_pj');
    var blocoPF = document.getElementById('bloco_pf');

    if (this.value === 'PJ') {
        blocoPJ.style.display = 'block';
        blocoPF.style.display = 'none';
    } else if (this.value === 'PF') {
        blocoPJ.style.display = 'none';
        blocoPF.style.display = 'block';
    } else {
        blocoPJ.style.display = 'none';
        blocoPF.style.display = 'none';
    }
});

var campoValor = document.getElementById('valor_servico_display');
var campoValorOculto = document.getElementById('valor_servico_hidden');

campoValor.addEventListener('input', function() {
    var somenteDigitos = campoValor.value.replace(/\D/g, '');
    if (somenteDigitos === '') {
        campoValor.value = '';
        campoValorOculto.value = '';
        return;
    }
    var valorCentavos = parseInt(somenteDigitos, 10);
    var valorReais = valorCentavos / 100;

    campoValorOculto.value = valorReais.toFixed(2);
    campoValor.value = 'R$ ' + valorReais.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
});
</script>
"""


@app.route('/solicitacao/servico-externo', methods=['GET', 'POST'])
@login_required
def servico_externo_form():
    if request.method == 'POST':
        valor_servico = float(request.form.get('valor_servico') or 0)

        solicitacao = Solicitacao(
            tipo='servico_externo',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_servico,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        prestador = PrestadorServico(
            solicitacao_id=solicitacao.id,
            tipo_prestador=request.form.get('tipo_prestador'),
            categoria_servico=request.form.get('categoria_servico'),
            nome_servico=request.form.get('nome_servico'),
            fornecedor_sugerido=request.form.get('fornecedor_sugerido'),
            especificacao=request.form.get('especificacao'),
            justificativa=request.form.get('justificativa'),
            valor_servico=valor_servico,
            nome_empresa=request.form.get('nome_empresa'),
            cnpj=request.form.get('cnpj'),
            nome_prestador=request.form.get('nome_prestador'),
            cpf_prestador=request.form.get('cpf_prestador'),
            rg_prestador=request.form.get('rg_prestador'),
            telefone_prestador=request.form.get('telefone_prestador'),
            pis_nis=request.form.get('pis_nis'),
            endereco_prestador=request.form.get('endereco_prestador'),
            banco=request.form.get('banco'),
            agencia=request.form.get('agencia'),
            conta=request.form.get('conta'),
            chave_pix=request.form.get('chave_pix'),
        )
        db.session.add(prestador)

        arquivos = request.files.getlist('anexos')
        for arquivo in arquivos:
            if arquivo and arquivo.filename:
                db.session.add(Anexo(
                    solicitacao_id=solicitacao.id,
                    nome_arquivo=arquivo.filename,
                    tipo_conteudo=arquivo.content_type,
                    dados=arquivo.read(),
                ))

        db.session.commit()
        flash('Solicitação de serviço externo enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = SERVICO_EXTERNO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__OPCOES_TIPOS_SERVICO__', montar_opcoes_tipos_servico())
    form_html = form_html.replace('__VALORES_SERVICO__', montar_dict_valores_servico())
    return render_pagina('Solicitação de Serviços Externos', form_html)


# ---------------- CADASTROS: SERVIÇOS EXTERNOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/servico-externo')
@login_required
def cadastro_servico_externo():
    somente_organizador()

    tipos = TipoServicoExterno.query.order_by(TipoServicoExterno.nome).all()
    linhas_html = ''
    for tipo in tipos:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_servico_externo_atualizar', tipo_id=tipo.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{tipo.nome}" style="width:200px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor" value="{tipo.valor}" style="width:100px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_servico_externo_excluir', tipo_id=tipo.id)}" style="display:inline;" onsubmit="return confirm('Excluir o serviço {tipo.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Tipos de Serviço Externo</h2>
    <table>
        <tr><th>Nome</th><th>Valor Referência (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar novo serviço</h3>
    <form method="POST" action="{url_for('cadastro_servico_externo_adicionar')}" style="max-width:400px;">
        <label>Nome do serviço:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor referência (R$):</label><br>
        <input type="number" step="0.01" name="valor" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar serviço</button>
    </form>
    """
    return render_pagina('Cadastro de Serviços Externos', conteudo)


@app.route('/cadastros/servico-externo/adicionar', methods=['POST'])
@login_required
def cadastro_servico_externo_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    valor = request.form.get('valor')

    if not nome:
        flash('Informe o nome do serviço.')
        return redirect(url_for('cadastro_servico_externo'))

    if TipoServicoExterno.query.filter_by(nome=nome).first():
        flash('Já existe um serviço com esse nome.')
        return redirect(url_for('cadastro_servico_externo'))

    db.session.add(TipoServicoExterno(nome=nome, valor=valor))
    db.session.commit()
    flash(f'Serviço "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/atualizar', methods=['POST'])
@login_required
def cadastro_servico_externo_atualizar(tipo_id):
    somente_organizador()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor = request.form.get('valor')
    db.session.commit()
    flash('Serviço externo atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_servico_externo_excluir(tipo_id):
    somente_organizador()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Serviço "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


# ---------------- CADASTROS: DIÁRIAS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/diaria')
@login_required
def cadastro_diaria():
    somente_organizador()

    areas = AreaDiaria.query.order_by(AreaDiaria.nome).all()
    auxilio_atual = obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)

    linhas_html = ''
    for area in areas:
        v_cheia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Cheia').first()
        v_meia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Meia').first()

        val_cheia = float(v_cheia.valor) if v_cheia else 0
        val_meia = float(v_meia.valor) if v_meia else 0

        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_diaria_atualizar', area_id=area.id)}" style="display:contents;">
            <td><input type="text" name="nome_area" value="{area.nome}" style="width:150px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_cheia" value="{val_cheia}" style="width:90px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_meia" value="{val_meia}" style="width:90px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_diaria_excluir', area_id=area.id)}" style="display:inline;" onsubmit="return confirm('Excluir a área {area.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Valores de Diárias por Área</h2>
    <table>
        <tr><th>Área / Região</th><th>Valor Cheia (R$)</th><th>Valor Meia (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova área</h3>
    <form method="POST" action="{url_for('cadastro_diaria_adicionar')}" style="max-width:400px; margin-bottom:30px;">
        <label>Nome da área:</label><br>
        <input type="text" name="nome_area" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor Diária Cheia (R$):</label><br>
        <input type="number" step="0.01" name="valor_cheia" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Valor Diária Meia (R$):</label><br>
        <input type="number" step="0.01" name="valor_meia" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar área</button>
    </form>

    <div class="bloco" style="max-width:400px;">
        <h3>Auxílio Deslocamento</h3>
        <form method="POST" action="{url_for('cadastro_diaria_auxilio')}">
            <label>Valor unitário do Auxílio Deslocamento (R$):</label><br>
            <input type="number" step="0.01" name="valor_auxilio" value="{auxilio_atual}" required style="padding:6px; width:150px; margin-bottom:10px;"><br>
            <button type="submit" class="btn btn-salvar">Atualizar Auxílio</button>
        </form>
    </div>
    """
    return render_pagina('Cadastro de Diárias', conteudo)


@app.route('/cadastros/diaria/adicionar', methods=['POST'])
@login_required
def cadastro_diaria_adicionar():
    somente_organizador()
    nome_area = request.form.get('nome_area', '').strip()
    valor_cheia = request.form.get('valor_cheia')
    valor_meia = request.form.get('valor_meia')

    if not nome_area:
        flash('Informe o nome da área.')
        return redirect(url_for('cadastro_diaria'))

    if AreaDiaria.query.filter_by(nome=nome_area).first():
        flash('Já existe uma área com esse nome.')
        return redirect(url_for('cadastro_diaria'))

    area = AreaDiaria(nome=nome_area)
    db.session.add(area)
    db.session.flush()

    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Cheia', valor=valor_cheia))
    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Meia', valor=valor_meia))

    db.session.commit()
    flash(f'Área "{nome_area}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/<int:area_id>/atualizar', methods=['POST'])
@login_required
def cadastro_diaria_atualizar(area_id):
    somente_organizador()
    area = AreaDiaria.query.get_or_404(area_id)
    area.nome = request.form.get('nome_area', '').strip()

    v_cheia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Cheia').first()
    if v_cheia:
        v_cheia.valor = request.form.get('valor_cheia')
    else:
        db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Cheia', valor=request.form.get('valor_cheia')))

    v_meia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Meia').first()
    if v_meia:
        v_meia.valor = request.form.get('valor_meia')
    else:
        db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Meia', valor=request.form.get('valor_meia')))

    db.session.commit()
    flash('Valores atualizados com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/<int:area_id>/excluir', methods=['POST'])
@login_required
def cadastro_diaria_excluir(area_id):
    somente_organizador()
    area = AreaDiaria.query.get_or_404(area_id)
    nome = area.nome
    db.session.delete(area)
    db.session.commit()
    flash(f'Área "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/auxilio', methods=['POST'])
@login_required
def cadastro_diaria_auxilio():
    somente_organizador()
    valor = request.form.get('valor_auxilio')

    config = Configuracao.query.filter_by(chave=CHAVE_VALOR_AUXILIO).first()
    if config:
        config.valor = valor
    else:
        db.session.add(Configuracao(chave=CHAVE_VALOR_AUXILIO, valor=valor))

    db.session.commit()
    flash('Valor do Auxílio Deslocamento atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


# ---------------- CADASTROS: COORDENAÇÕES (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/coordenacao')
@login_required
def cadastro_coordenacao():
    somente_organizador()

    coordenacoes = Coordenacao.query.order_by(Coordenacao.nome).all()
    linhas_html = ''
    for coord in coordenacoes:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_coordenacao_atualizar', coord_id=coord.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{coord.nome}" style="width:250px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_coordenacao_excluir', coord_id=coord.id)}" style="display:inline;" onsubmit="return confirm('Excluir a coordenação {coord.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Coordenações Solicitantes</h2>
    <table>
        <tr><th>Nome</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova coordenação</h3>
    <form method="POST" action="{url_for('cadastro_coordenacao_adicionar')}" style="max-width:400px;">
        <label>Nome da coordenação:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar coordenação</button>
    </form>
    """
    return render_pagina('Cadastro de Coordenação', conteudo)


@app.route('/cadastros/coordenacao/adicionar', methods=['POST'])
@login_required
def cadastro_coordenacao_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()

    if not nome:
        flash('Informe o nome da coordenação.')
        return redirect(url_for('cadastro_coordenacao'))

    if Coordenacao.query.filter_by(nome=nome).first():
        flash('Já existe uma coordenação com esse nome.')
        return redirect(url_for('cadastro_coordenacao'))

    db.session.add(Coordenacao(nome=nome))
    db.session.commit()
    flash(f'Coordenação "{nome}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coord_id>/atualizar', methods=['POST'])
@login_required
def cadastro_coordenacao_atualizar(coord_id):
    somente_organizador()
    coord = Coordenacao.query.get_or_404(coord_id)
    coord.nome = request.form.get('nome', '').strip()
    db.session.commit()
    flash('Coordenação atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coord_id>/excluir', methods=['POST'])
@login_required
def cadastro_coordenacao_excluir(coord_id):
    somente_organizador()
    coord = Coordenacao.query.get_or_404(coord_id)
    nome = coord.nome
    db.session.delete(coord)
    db.session.commit()
    flash(f'Coordenação "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


# ---------------- INICIALIZAÇÃO E SEED DO BANCO DE DADOS ----------------
def inicializar_banco():
    with app.app_context():
        db.create_all()

        # Seed do usuário administrador padrão
        if not Usuario.query.filter_by(email='admin@carajas.org').first():
            admin = Usuario(
                nome='Administrador',
                email='admin@carajas.org',
                is_organizador=True,
                is_aprovador=True,
                perfil='analista',
            )
            admin.set_senha('admin123')
            db.session.add(admin)

        # Seed das áreas e valores padrão de diária
        for area_nome, valores in AREAS_PADRAO.items():
            area = AreaDiaria.query.filter_by(nome=area_nome).first()
            if not area:
                area = AreaDiaria(nome=area_nome)
                db.session.add(area)
                db.session.flush()

                for tipo, valor in valores.items():
                    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria=tipo, valor=valor))

        # Seed da configuração padrão do auxílio deslocamento
        if not Configuracao.query.filter_by(chave=CHAVE_VALOR_AUXILIO).first():
            db.session.add(Configuracao(chave=CHAVE_VALOR_AUXILIO, valor=VALOR_AUXILIO_PADRAO))

        db.session.commit()


if __name__ == '__main__':
    inicializar_banco()
    app.run(debug=True)
