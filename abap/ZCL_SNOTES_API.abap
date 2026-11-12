*&---------------------------------------------------------------------*
*& ZCL_SNOTES_API - REST wrapper around SNOTE / SCWB_* function modules.
*& Expose via SICF node /sap/bc/rest/zsnotes  (handler = ZCL_SNOTES_API).
*&
*& Routes (parsed from path info):
*&   GET /list?since=YYYY-MM-DD&components=FI-LOC-BR,SD-BIL-GT-BR&page=1
*&   GET /note/{note_number}
*&
*& Auth: delegated to SICF node (Basic Auth technical user recommended;
*&       OAuth2 via /sap/bc/sec/oauth2 token endpoint if available).
*&
*& Minimal skeleton — adjust FM calls to your release (SCWN_* vs SCWB_*).
*&---------------------------------------------------------------------*
CLASS zcl_snotes_api DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC.

  PUBLIC SECTION.
    INTERFACES if_http_extension.

  PRIVATE SECTION.
    METHODS handle_list
      IMPORTING io_req TYPE REF TO if_http_request
                io_rsp TYPE REF TO if_http_response.
    METHODS handle_note
      IMPORTING iv_note TYPE string
                io_rsp  TYPE REF TO if_http_response.
    METHODS json_error
      IMPORTING io_rsp  TYPE REF TO if_http_response
                iv_code TYPE i
                iv_msg  TYPE string.
ENDCLASS.

CLASS zcl_snotes_api IMPLEMENTATION.

  METHOD if_http_extension~handle_request.
    DATA(lv_path) = server->request->get_header_field( '~path_info' ).
    DATA(lv_method) = server->request->get_header_field( '~request_method' ).

    IF lv_method <> 'GET'.
      json_error( io_rsp = server->response iv_code = 405 iv_msg = 'Method Not Allowed' ).
      RETURN.
    ENDIF.

    IF lv_path CP '/list*'.
      handle_list( io_req = server->request io_rsp = server->response ).
    ELSEIF lv_path CP '/note/*'.
      DATA(lv_note) = substring_after( val = lv_path sub = '/note/' ).
      handle_note( iv_note = lv_note io_rsp = server->response ).
    ELSE.
      json_error( io_rsp = server->response iv_code = 404 iv_msg = 'Not Found' ).
    ENDIF.
  ENDMETHOD.

  METHOD handle_list.
    DATA: lv_since      TYPE d,
          lv_since_raw  TYPE string,
          lv_components TYPE string,
          lv_page       TYPE i VALUE 1,
          lv_page_size  TYPE i VALUE 100.

    lv_since_raw = io_req->get_form_field( 'since' ).
    IF strlen( lv_since_raw ) >= 10.
      lv_since = lv_since_raw+0(4) && lv_since_raw+5(2) && lv_since_raw+8(2).
    ENDIF.
    lv_components = io_req->get_form_field( 'components' ).
    DATA(lv_page_str) = io_req->get_form_field( 'page' ).
    IF lv_page_str IS NOT INITIAL.
      lv_page = CONV i( lv_page_str ).
    ENDIF.

    " TODO: Replace with real FM call that lists notes by date range + component.
    " Candidates:
    "   SCWB_NOTE_SEARCH            (older releases)
    "   SCWN_NOTE_READ / SCWN_API_* (newer, SAP for Me-aligned)
    " Fallback: SELECT from CWBNTSTAT / CWBNTHEAD if those tables are available.
    TYPES: BEGIN OF ty_note,
             note_number  TYPE string,
             title        TYPE string,
             component    TYPE string,
             priority     TYPE string,
             category     TYPE string,
             released_on  TYPE string,
             version      TYPE i,
           END OF ty_note.
    DATA: lt_notes TYPE STANDARD TABLE OF ty_note,
          lv_has_more TYPE abap_bool.

    " *** CHAMADA REAL AQUI ***
    " CALL FUNCTION 'SCWB_NOTE_SEARCH'
    "   EXPORTING  ...
    "   TABLES     et_notes = lt_internal.
    " Mapear lt_internal -> lt_notes; definir lv_has_more se vier próxima página.

    " Monta JSON (SAP_2_JSON disponível em releases >= 7.40):
    DATA lv_json TYPE string.
    CALL TRANSFORMATION id SOURCE notes = lt_notes has_more = lv_has_more
                          RESULT XML lv_json
                          OPTIONS data_refs = 'embedded'.

    io_rsp->set_content_type( 'application/json; charset=utf-8' ).
    io_rsp->set_cdata( lv_json ).
    io_rsp->set_status( code = 200 reason = 'OK' ).
  ENDMETHOD.

  METHOD handle_note.
    DATA: lv_note_c TYPE cwbntnumbr,
          lv_json   TYPE string.
    lv_note_c = iv_note.

    " TODO: ler cabeçalho + long text + válidades + objetos + pré-requisitos.
    " FMs candidatos:
    "   SCWN_NOTE_READ           (header + text)
    "   SCWB_NOTE_READ_LONGTEXT  (long text)
    "   SCWB_API_NOTES_GET       (metadata)
    " Tabelas: CWBNTHEAD, CWBNTCUST, CWBNTREL (releases), CWBOBJECT (objetos).

    TYPES: BEGIN OF ty_release,
             software_component TYPE string,
             release            TYPE string,
             sp_from            TYPE string,
             sp_to              TYPE string,
           END OF ty_release,
           BEGIN OF ty_object,
             obj_type     TYPE string,
             obj_name     TYPE string,
             version_from TYPE string,
             version_to   TYPE string,
           END OF ty_object,
           BEGIN OF ty_payload,
             note_number TYPE string,
             title       TYPE string,
             component   TYPE string,
             priority    TYPE string,
             category    TYPE string,
             released_on TYPE string,
             version     TYPE i,
             long_text   TYPE string,
             releases    TYPE STANDARD TABLE OF ty_release WITH DEFAULT KEY,
             objects     TYPE STANDARD TABLE OF ty_object  WITH DEFAULT KEY,
             prereqs     TYPE STANDARD TABLE OF string     WITH DEFAULT KEY,
           END OF ty_payload.
    DATA ls_payload TYPE ty_payload.
    ls_payload-note_number = iv_note.

    " *** POPULAR ls_payload AQUI ***

    CALL TRANSFORMATION id SOURCE data = ls_payload
                          RESULT XML lv_json
                          OPTIONS data_refs = 'embedded'.

    io_rsp->set_content_type( 'application/json; charset=utf-8' ).
    io_rsp->set_cdata( lv_json ).
    io_rsp->set_status( code = 200 reason = 'OK' ).
  ENDMETHOD.

  METHOD json_error.
    io_rsp->set_content_type( 'application/json; charset=utf-8' ).
    io_rsp->set_cdata( |\{"error":"{ iv_msg }"\}| ).
    io_rsp->set_status( code = iv_code reason = iv_msg ).
  ENDMETHOD.

ENDCLASS.
