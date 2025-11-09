# frozen_string_literal: true

require 'spec_helper'
require 'rack/test'
require 'json'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'returns healthy status for all services when dependencies are healthy' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', timeout: 2)
        .and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']).to be_a(Hash)
      expect(body['services']['ruby']['status']).to eq('healthy')
      expect(body['services']['go']['status']).to eq('healthy')
      expect(body['services']['python']['status']).to eq('healthy')
    end

    it 'marks services as unhealthy or unreachable based on dependency responses' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', timeout: 2)
        .and_return(double(code: 500))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', timeout: 2)
        .and_raise(StandardError.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['go']['status']).to eq('unhealthy')
      expect(body['services']['python']['status']).to eq('unreachable')
      expect(body['services']['python']['error']).to include('timeout')
    end
  end

  describe 'POST /diff' do
    it 'returns diff and new code review for valid payload' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(:old_content, :new_content))
        .and_return({ 'changes' => [{ 'line' => 1, 'type' => 'added' }] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 92.5, 'issues' => [] })

      payload = { old_content: 'old', new_content: 'new' }
      post '/diff', payload.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq('changes' => [{ 'line' => 1, 'type' => 'added' }])
      expect(body['new_code_review']).to eq('score' => 92.5, 'issues' => [])
    end

    it 'returns 400 when required fields are missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing old_content or new_content')
    end
  end

  describe 'POST /metrics' do
    it 'returns metrics, review, and calculated overall quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(:content))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 80, 'issues' => %w[a b] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to eq('complexity' => 1)
      expect(body['review']).to eq('score' => 80, 'issues' => %w[a b])
      expect(body['overall_quality']).to eq(0.0)
    end

    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns dashboard stats and summary with calculated health score' do
      file_stats = {
        'total_files' => 5,
        'total_lines' => 1000,
        'languages' => { 'ruby' => 3, 'python' => 2 }
      }
      review_stats = {
        'average_score' => 90.0,
        'total_issues' => 10,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(:files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(:files))
        .and_return(review_stats)

      files_payload = { files: [{ path: 'a.rb', content: 'puts :ok' }, { path: 'b.py', content: 'print("ok")' }] }
      post '/dashboard', files_payload.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['timestamp']).to be_a(String)
      expect(body['file_statistics']).to eq(file_stats)
      expect(body['review_statistics']).to eq(review_stats)
      expect(body['summary']['total_files']).to eq(5)
      expect(body['summary']['total_lines']).to eq(1000)
      expect(body['summary']['languages']).to eq('ruby' => 3, 'python' => 2)
      expect(body['summary']['average_quality_score']).to eq(90.0)
      expect(body['summary']['total_issues']).to eq(10)
      expect(body['summary']['health_score']).to eq(71.0)
    end

    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end
  end
end
