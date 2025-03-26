import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import os
import glob
from typing import List, Dict, Optional, Tuple
import json
import base64
import datetime


# Configurações da página
st.set_page_config(
    page_title="ImportadorANS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS 
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #0D47A1;
        margin-bottom: 1rem;
    }
    .success-message {
        background-color: #DCEDC8;
        padding: 1rem;
        border-radius: 5px;
        font-weight: bold;
        color: #33691E;
    }
    .error-message {
        background-color: #FFCDD2;
        padding: 1rem;
        border-radius: 5px;
        font-weight: bold;
        color: #B71C1C;
    }
</style>
""", unsafe_allow_html=True)

# Título principal
st.markdown("<h1 class='main-header'>ImportadorANS</h1>", unsafe_allow_html=True)
st.markdown("#### Ferramenta para importação de dados da ANS para bancos PostgreSQL")

# Inicializar estados de sessão
if 'connection_established' not in st.session_state:
    st.session_state.connection_established = False
if 'engine' not in st.session_state:
    st.session_state.engine = None
if 'conn' not in st.session_state:
    st.session_state.conn = None
if 'preview_data' not in st.session_state:
    st.session_state.preview_data = None
if 'columns_info' not in st.session_state:
    st.session_state.columns_info = {}
if 'ai_suggested_types' not in st.session_state:
    st.session_state.ai_suggested_types = {}
if 'import_log' not in st.session_state:
    st.session_state.import_log = []

# Funções de conexão e utilidades
def create_connection(db_config):
    """Cria conexão com o banco de dados PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password']
        )
        st.success("Conexão com PostgreSQL estabelecida com sucesso!")
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar ao PostgreSQL: {e}")
        return None

def create_sqlalchemy_engine(db_config):
    """Cria engine SQLAlchemy para operações com pandas"""
    try:
        conn_string = f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        engine = create_engine(conn_string)
        return engine
    except Exception as e:
        st.error(f"Erro ao criar SQLAlchemy engine: {e}")
        return None

def check_table_exists(conn, table_name):
    """Verifica se a tabela já existe no banco de dados"""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_name = %s
            );
        """, (table_name,))
        exists = cursor.fetchone()[0]
        return exists
    except Exception as e:
        st.error(f"Erro ao verificar se a tabela existe: {e}")
        return False

def get_all_files(directory, pattern="*.csv"):
    """Obtém todos os arquivos em um diretório que correspondem ao padrão"""
    try:
        files = glob.glob(os.path.join(directory, pattern))
        return files
    except Exception as e:
        st.error(f"Erro ao buscar arquivos: {e}")
        return []

def read_csv_preview(file_path, sep=';', encoding='utf-8', nrows=5):
    """Lê uma prévia do CSV para exibição"""
    try:
        df = pd.read_csv(file_path, sep=sep, encoding=encoding, nrows=nrows, low_memory=False)
        return df
    except Exception as e:
        st.error(f"Erro ao ler prévia do arquivo {os.path.basename(file_path)}: {e}")
        return None

def suggest_column_types(df):
    """Sugere tipos apropriados para cada coluna com base nos dados"""
    suggestions = {}
    for col in df.columns:
        if df[col].dtype == 'int64':
            # Verificar se é um código que deve ser string
            if col.startswith('CD_') or 'CODIGO' in col.upper():
                suggestions[col] = 'text'
            else:
                suggestions[col] = 'integer'
        elif df[col].dtype == 'float64':
            # Verificar se parece um código com decimais indesejados
            if col.startswith('CD_') or 'CODIGO' in col.upper():
                suggestions[col] = 'text'
            else:
                suggestions[col] = 'float'
        elif df[col].dtype == 'object':
            # Verificar se é uma data
            if 'DATA' in col.upper() or 'DT_' in col.upper():
                suggestions[col] = 'date'
            else:
                suggestions[col] = 'text'
        else:
            suggestions[col] = 'text'
    
    return suggestions

def ask_anthropic_for_column_types(df, api_key):
    """Usa a API da Anthropic para sugerir tipos de colunas com base em uma amostra dos dados"""
    if not api_key:
        return {}
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        # Preparar amostra de dados para enviar à API
        sample = df.head(5).to_string()
        column_names = df.columns.tolist()
        dtypes = {col: str(df[col].dtype) for col in column_names}
        
        prompt = f"""
        Aqui está uma amostra de um DataFrame do pandas com alguns dados da ANS (Agência Nacional de Saúde Suplementar):
        
        {sample}
        
        Os nomes das colunas são: {column_names}
        Os tipos atuais inferidos pelo pandas são: {dtypes}
        
        Para importação em um banco PostgreSQL, preciso saber quais tipos SQL seriam mais apropriados para cada coluna.
        
        Algumas observações importantes:
        1. Colunas que começam com 'CD_' ou contêm 'CODIGO'/'COD' geralmente são códigos identificadores e devem ser tratados como 'text', mesmo se parecerem números
        2. Colunas que começam com 'DT_' ou contêm 'DATA' geralmente são datas
        3. Se uma coluna numérica tem valores como 336025.0 e é um código ou identificador, essa coluna deve ser 'text' (não INTEGER ou FLOAT)
        
        Por favor, retorne sua resposta em formato JSON, onde a chave é o nome da coluna e o valor é o tipo SQL recomendado ('text', 'integer', 'float', 'date', etc).
        """
        
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            temperature=0,
            system="Você é um especialista em análise de dados e bancos de dados SQL.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response = message.content[0].text
        
        # Extrair o JSON da resposta
        import re
        json_match = re.search(r'{.*}', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            return json.loads(json_str)
        else:
            st.warning("Não foi possível extrair sugestões de tipos da resposta da IA.")
            return {}
            
    except Exception as e:
        st.error(f"Erro ao consultar IA para tipos de colunas: {e}")
        return {}

def process_and_import_files(files, table_name, sep, encoding, column_types, if_exists, date_columns=None):
    """Processa e importa os arquivos para o banco de dados"""
    
    if not st.session_state.connection_established:
        st.error("Não há conexão com o banco de dados.")
        return
    
    log = []
    total_records = 0
    
    # Verificar se a tabela existe
    table_exists = check_table_exists(st.session_state.conn, table_name)
    log.append(f"Tabela '{table_name}' existe: {table_exists}")
    
    for index, file_path in enumerate(files):
        file_name = os.path.basename(file_path)
        log.append(f"Processando arquivo: {file_name}")
        
        # Criar uma barra de progresso para cada arquivo
        progress_bar = st.progress(0)
        
        try:
            # Ler o arquivo CSV completo em partes
            reader = pd.read_csv(file_path, sep=sep, encoding=encoding, low_memory=False, chunksize=10000)
            
            file_records = 0
            for chunk in reader:
                # Aplicar conversões de tipo
                for col, col_type in column_types.items():
                    if col in chunk.columns:
                        if col_type == 'text':
                            chunk[col] = chunk[col].astype(str)
                            # Remover .0 de valores numéricos convertidos para string
                            chunk[col] = chunk[col].str.replace('.0$', '', regex=True)
                        elif col_type == 'integer':
                            chunk[col] = pd.to_numeric(chunk[col], errors='coerce').fillna(0).astype(int)
                        elif col_type == 'float':
                            chunk[col] = pd.to_numeric(chunk[col], errors='coerce')
                        elif col_type == 'date' and col in date_columns:
                            chunk[col] = pd.to_datetime(chunk[col], errors='coerce')
                
                # Criar tabela se não existir
                if not table_exists and if_exists != 'append_only':
                    log.append(f"Criando tabela '{table_name}' com base no primeiro arquivo...")
                    try:
                        # Criar tabela sem inserir dados
                        chunk.head(0).to_sql(table_name, st.session_state.engine, if_exists='fail', index=False)
                        table_exists = True
                        log.append(f"Tabela '{table_name}' criada com sucesso!")
                    except Exception as e:
                        log.append(f"Erro ao criar tabela: {e}")
                        if 'already exists' in str(e):
                            table_exists = True
                            log.append(f"Tabela já existe, continuando com a importação.")
                        else:
                            raise e
                
                # Importar dados
                if if_exists == 'replace' and table_exists and files.index(file_path) == 0:
                    # Truncar a tabela apenas na primeira iteração
                    mode = 'replace'
                    log.append(f"Substituindo dados na tabela '{table_name}'.")
                else:
                    mode = 'append'
                    log.append(f"Adicionando dados à tabela '{table_name}'.")
                
                # Verificar se os dados já existem na tabela
                existing_data = pd.read_sql(f"SELECT CD_OPERADORA FROM {table_name}", st.session_state.conn)
                
                # Filtrar o chunk para inserir apenas os registros que não existem na tabela
                new_data = chunk[~chunk['CD_OPERADORA'].isin(existing_data['CD_OPERADORA'])]
                
                try:
                    new_data.to_sql(table_name, st.session_state.engine, if_exists=mode, index=False)
                    file_records += len(new_data)
                    total_records += len(new_data)
                except Exception as import_error:
                    log.append(f"Erro ao importar chunk: {import_error}")
                
                # Atualizar a barra de progresso
                total_rows = len(pd.read_csv(file_path, sep=sep, encoding=encoding, low_memory=False))
                progress = (file_records / total_rows)
                progress_bar.progress(progress)
            
            log.append(f"Dados do arquivo {file_name} importados com sucesso! {file_records} registros inseridos.")
            
        except Exception as e:
            log.append(f"ERRO ao processar arquivo {file_name}: {e}")
            # Tentar reconectar ao banco de dados
            try:
                st.session_state.conn = create_connection(db_config)
                st.session_state.engine = create_sqlalchemy_engine(db_config)
                log.append("Conexão com o banco de dados reestabelecida.")
            except Exception as reconnect_error:
                log.append(f"Erro ao reconectar ao banco de dados: {reconnect_error}")
        
        # Exibir o log do arquivo após o processamento
        st.code("\n".join(log[-2:]))
    
    log.append(f"Processo concluído! Total de {total_records} registros importados de {len(files)} arquivos.")
    log.append("Hospedar os arquivos base no servidor onde o banco de dados está localizado geralmente é mais rápido, pois elimina a necessidade de transferir os dados pela rede.")
    return log

# Sidebar para conexão ao banco de dados
with st.sidebar:
    st.subheader("Configurações de Conexão")
    
    db_host = st.text_input("Host", value="146.235.222.230", key="db_host")
    db_port = st.text_input("Porta", value="5432", key="db_port")
    db_name = st.text_input("Nome do Banco", value="ans", key="db_name")
    db_user = st.text_input("Usuário", value="vcollos", key="db_user")
    db_password = st.text_input("Senha", value="Essaaqui:#01", type="password", key="db_password")
    
    db_config = {
        'host': db_host,
        'port': db_port,
        'database': db_name,
        'user': db_user,
        'password': db_password
    }
    
    if st.button("Conectar ao Banco"):
        conn = create_connection(db_config)
        if conn:
            engine = create_sqlalchemy_engine(db_config)
            if engine:
                st.session_state.conn = conn
                st.session_state.engine = engine
                st.session_state.connection_established = True
    
    st.divider()
    
    # Opções avançadas
    st.subheader("Opções Avançadas")
    
    # Chave API Anthropic
    anthropic_api_key = st.text_input("Chave API Anthropic (opcional)", type="password", key="anthropic_api_key")
    
    # Opções de definição de schema
    st.subheader("Definição de Schema")
    schema_option = st.radio(
        "Como definir o schema da tabela?",
        options=["Automático", "Arquivo Schema CSV", "Modelo de Schema Salvo"],
        index=0,
        help="Automático: detecta automaticamente os tipos. Arquivo Schema CSV: suba um arquivo CSV com definições. Modelo: use um schema salvo anteriormente."
    )
    
    if schema_option == "Arquivo Schema CSV":
        schema_file = st.file_uploader("Arquivo de Schema (CSV)", type=['csv'])
        if schema_file is not None:
            try:
                schema_df = pd.read_csv(schema_file)
                st.session_state.schema_definition = {}
                for _, row in schema_df.iterrows():
                    if 'column_name' in row and 'data_type' in row:
                        st.session_state.schema_definition[row['column_name']] = row['data_type']
                st.success(f"Schema carregado com {len(st.session_state.schema_definition)} definições de coluna.")
                st.dataframe(schema_df)
            except Exception as e:
                st.error(f"Erro ao carregar arquivo de schema: {e}")
    
    elif schema_option == "Modelo de Schema Salvo":
        schema_models = st.selectbox(
            "Selecione um modelo de schema",
            options=["Prestadores Não Hospitalares", "Prestadores Hospitalares", "Cidades", "Operadoras", "Beneficiários"],
            index=0
        )
        
        # Schemas pré-definidos para diferentes tipos de dados da ANS
        predefined_schemas = {
            "Prestadores Não Hospitalares": {
                "CD_OPERADORA": "text",
                "NM_FANTASIA_PRESTADOR": "text",
                "NM_RAZAO_SOCIAL": "text",
                "NU_CNPJ": "text",
                "TP_IDENTIFICADOR": "text",
                "TP_PRESTADOR": "text",
                "TP_CLASSIFICACAO_PRESTADOR": "text",
                "DT_VINCULO_OPERADORA_INICIO": "date",
                "DT_VINCULO_OPERADORA_FIM": "date",
                "DT_ATUALIZACAO": "date"
            },
            "Prestadores Hospitalares": {
                "CD_OPERADORA": "text",
                "NM_FANTASIA_PRESTADOR": "text",
                "NM_RAZAO_SOCIAL": "text",
                "NU_CNPJ": "text",
                "TP_IDENTIFICADOR": "text",
                "TP_CONTRATACAO": "text",
                "TP_CLASSIFICACAO_PRESTADOR": "text",
                "QT_LEITOS_TOTAL": "integer",
                "QT_LEITOS_SUS": "integer",
                "QT_LEITOS_NAO_SUS": "integer",
                "DT_VINCULO_OPERADORA_INICIO": "date",
                "DT_VINCULO_OPERADORA_FIM": "date",
                "DT_ATUALIZACAO": "date"
            },
            "Cidades": {
                "CD_MUNICIPIO": "text",
                "NM_MUNICIPIO": "text",
                "SG_UF": "text",
                "NO_UF": "text",
                "NO_REGIAO": "text"
            },
            "Operadoras": {
                "CD_OPERADORA": "text",
                "NM_FANTASIA": "text",
                "NM_RAZAO_SOCIAL": "text",
                "NU_CNPJ": "text",
                "TP_CLASSIFICACAO": "text",
                "TP_NATUREZA_JUR": "text",
                "SG_UF": "text",
                "CD_MUNICIPIO": "text",
                "NM_MUNICIPIO": "text",
                "DT_REGISTRO_ANS": "date",
                "DT_CANCELAMENTO": "date",
                "DT_ATUALIZACAO": "date"
            },
            "Beneficiários": {
                "CD_OPERADORA": "text",
                "NM_OPERADORA": "text",
                "CD_CONTA_CONTRATANTE": "text",
                "TP_CONTA_CONTRATANTE": "text",
                "CD_MUNICIPIO": "text",
                "UF_BENEFICIARIO": "text",
                "FAIXA_ETARIA": "text",
                "QT_BENEFICIARIOS": "integer",
                "COMPETENCIA": "text",
                "DT_ATUALIZACAO": "date"
            }
        }
        
        if schema_models in predefined_schemas:
            st.session_state.schema_definition = predefined_schemas[schema_models]
            st.success(f"Schema '{schema_models}' carregado com {len(st.session_state.schema_definition)} definições de coluna.")
            
            # Mostrar o schema em uma tabela
            schema_display = pd.DataFrame([
                {"Coluna": col, "Tipo de Dado": tipo} 
                for col, tipo in st.session_state.schema_definition.items()
            ])
            st.dataframe(schema_display)
    else:
        # Se for automático, limpamos qualquer schema existente
        if 'schema_definition' in st.session_state:
            del st.session_state.schema_definition
    
    # Opção para exportar o schema atual
    if st.session_state.preview_data is not None and st.button("Exportar Schema Atual"):
        if 'ai_suggested_types' in st.session_state and st.session_state.ai_suggested_types:
            schema_export = pd.DataFrame([
                {"column_name": col, "data_type": tipo} 
                for col, tipo in st.session_state.ai_suggested_types.items()
            ])
            
            csv = schema_export.to_csv(index=False)
            b64 = base64.b64encode(csv.encode()).decode()
            href = f'<a href="data:file/csv;base64,{b64}" download="schema_definition.csv">Baixar Schema CSV</a>'
            st.markdown(href, unsafe_allow_html=True)
    
    # Link para documentação
    st.markdown("""
    **Links Úteis:**
    * [Documentação da ANS](https://www.gov.br/ans/pt-br)
    * [Documentação PostgreSQL](https://www.postgresql.org/docs/)
    """)

# Principal - Formulário de importação
st.markdown("<h2 class='sub-header'>Configuração de Importação</h2>", unsafe_allow_html=True)

# Formulário principal
with st.form("importacao_form"):
    # Caminho do diretório
    dir_path = st.text_input("Diretório dos Arquivos", value="/Volumes/M1_SSD/DEV/ANS/Arquivos/")
    
    # Padrão de arquivo
    file_pattern = st.text_input("Padrão de Arquivo", value="*.csv", 
                                help="Use curingas como *.csv ou padrões específicos como cidades*.csv")
    
    # Nome da tabela
    table_name = st.text_input("Nome da Tabela de Destino", value="cidades")
    
    # Opções de separador e codificação
    col1, col2 = st.columns(2)
    with col1:
        separator = st.selectbox("Separador", options=[",", ";", "\\t"], 
                                format_func=lambda x: {"," : "Vírgula (,)", 
                                                      ";" : "Ponto e Vírgula (;)", 
                                                      "\\t" : "Tab (\\t)"}[x],
                                index=0)
    with col2:
        encoding = st.selectbox("Codificação", options=["utf-8", "latin1", "cp1252", "iso-8859-1"], index=0)
    
    # Opção de comportamento se a tabela existir
    if_exists = st.radio("Se a tabela já existir:", 
                        options=["append", "replace", "append_only"],
                        format_func=lambda x: {"append": "Adicionar dados (criar se não existir)", 
                                             "replace": "Substituir dados", 
                                             "append_only": "Adicionar dados (não tentar criar)"}[x])
    
    # Botão para carregar preview
    submitted = st.form_submit_button("Analisar Arquivos")
    
    if submitted:
        if not os.path.isdir(dir_path):
            st.error(f"O diretório {dir_path} não existe.")
        else:
            files = get_all_files(dir_path, file_pattern)
            if not files:
                st.error(f"Nenhum arquivo encontrado com o padrão '{file_pattern}' no diretório informado.")
            else:
                st.success(f"Encontrados {len(files)} arquivos.")
                
                # Mostrar o primeiro arquivo como prévia
                st.session_state.preview_data = read_csv_preview(files[0], separator, encoding)
                if st.session_state.preview_data is not None:
                    # Sugerir tipos de coluna
                    st.session_state.columns_info = {
                        col: {'original_type': str(st.session_state.preview_data[col].dtype)} 
                        for col in st.session_state.preview_data.columns
                    }
                    
                    # Sugestões automáticas de tipos
                    basic_suggestions = suggest_column_types(st.session_state.preview_data)
                    
                    # Se a chave API da Anthropic foi fornecida, obter sugestões mais avançadas
                    if anthropic_api_key:
                        ai_suggestions = ask_anthropic_for_column_types(
                            st.session_state.preview_data, 
                            anthropic_api_key
                        )
                        # Combinar sugestões, priorizando as da IA
                        st.session_state.ai_suggested_types = {**basic_suggestions, **ai_suggestions}
                    else:
                        st.session_state.ai_suggested_types = basic_suggestions

# Exibir prévia e configurar tipos de dados
if st.session_state.preview_data is not None:
    st.markdown("<h2 class='sub-header'>Prévia dos Dados</h2>", unsafe_allow_html=True)
    st.dataframe(st.session_state.preview_data)
    
    st.markdown("<h2 class='sub-header'>Configuração de Tipos de Dados</h2>", unsafe_allow_html=True)
    st.markdown("""
    Configure os tipos de dados para cada coluna. Colunas que começam com 'CD_' geralmente 
    devem ser tratadas como texto, mesmo que contenham apenas números.
    """)
    
    # Formulário de configuração de tipos
    with st.form("data_types_form"):
        # Lista para armazenar colunas de data
        date_columns = []
        
        # Dicionário para armazenar os tipos selecionados
        column_types = {}
        
        # Para cada coluna, mostrar um seletor de tipo
        cols = list(st.session_state.columns_info.keys())
        
        # Organizar em 3 colunas para economizar espaço
        col_groups = [cols[i:i+3] for i in range(0, len(cols), 3)]
        
        for group in col_groups:
            columns = st.columns(len(group))
            for i, col_name in enumerate(group):
                with columns[i]:
                    original_type = st.session_state.columns_info[col_name]['original_type']
                    suggested_type = st.session_state.ai_suggested_types.get(col_name, 'text')
                    
                    # Definir o índice padrão com base na sugestão
                    default_index = 0  # text por padrão
                    if suggested_type == 'integer':
                        default_index = 1
                    elif suggested_type == 'float':
                        default_index = 2
                    elif suggested_type == 'date':
                        default_index = 3
                        
                    st.write(f"**{col_name}**")
                    st.caption(f"Tipo original: {original_type}")
                    st.caption(f"Sugerido: {suggested_type}")
                    
                    selected_type = st.selectbox(
                        f"Tipo para {col_name}",
                        options=["text", "integer", "float", "date"],
                        index=default_index,
                        key=f"type_{col_name}"
                    )
                    
                    column_types[col_name] = selected_type
                    
                    # Se for data, adicionar à lista de colunas de data
                    if selected_type == 'date':
                        date_columns.append(col_name)
        
        # Botão para iniciar importação
        import_submitted = st.form_submit_button("Iniciar Importação")
        
        if import_submitted:
            if not st.session_state.connection_established:
                st.error("É necessário estabelecer conexão com o banco de dados primeiro.")
            else:
                # Obter lista de arquivos novamente
                files = get_all_files(dir_path, file_pattern)
                if not files:
                    st.error("Nenhum arquivo encontrado.")
                else:
                    # Iniciar importação
                    with st.spinner('Importando dados...'):
                        log = process_and_import_files(
                            files=files,
                            table_name=table_name,
                            sep=separator,
                            encoding=encoding,
                            column_types=column_types,
                            if_exists=if_exists,
                            date_columns=date_columns
                        )
                        # Armazenar log
                        st.session_state.import_log = log
                    
                    # Exibir mensagem de sucesso e log
                    st.success("Importação concluída!")

# Exibir log de importação se disponível
if st.session_state.import_log:
    st.markdown("<h2 class='sub-header'>Log de Importação</h2>", unsafe_allow_html=True)
    st.code("\n".join(st.session_state.import_log))
    
    # Opção para salvar o log em arquivo
    if st.button("Salvar Log"):
        log_text = "\n".join(st.session_state.import_log)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"import_log_{timestamp}.txt"
        
        b64 = base64.b64encode(log_text.encode()).decode()
        href = f'<a href="data:file/txt;base64,{b64}" download="{filename}">Clique aqui para baixar o log</a>'
        st.markdown(href, unsafe_allow_html=True)

# Rodapé
st.markdown("---")
st.caption("© 2025 ImportadorANS - Desenvolvido para importação de dados ANS")
