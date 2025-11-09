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

    it 'returns 400 when content is missing' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'uses detected language based on file extension' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ["puts 'hi'"] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts 1'))
        .and_return({ 'score' => 100, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end

    it 'falls back to params when JSON body is invalid' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['print(1)'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/analyze?content=print(1)&path=main.py', 'invalid_json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']).to include('review_score' => 90)
    end
  end

  describe 'GET /status' do
    it 'returns health status for services including unreachable' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', timeout: 2)
        .and_raise(StandardError.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['ruby']['status']).to eq('healthy')
      expect(json['services']['go']['status']).to eq('healthy')
      expect(json['services']['python']['status']).to eq('unreachable')
      expect(json['services']['python']).to have_key('error')
    end

    it 'marks service as unhealthy when non-200 code is returned' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', timeout: 2)
        .and_return(double(code: 500))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', timeout: 2)
        .and_return(double(code: 503))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['go']['status']).to eq('unhealthy')
      expect(json['services']['python']['status']).to eq('unhealthy')
    end
  end

  describe 'POST /diff' do
    it 'returns diff and new review for valid input' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(:old_content, :new_content))
        .and_return({ 'changes' => [{ 'type' => 'add', 'line' => 1 }] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 75, 'issues' => ['nit'] })

      post '/diff', { old_content: 'a', new_content: 'a+b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json).to have_key('diff')
      expect(json).to have_key('new_code_review')
      expect(json['diff']['changes']).to be_an(Array)
      expect(json['new_code_review']['score']).to eq(75)
    end

    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing old_content or new_content')
    end
  end

  describe 'POST /metrics' do
    it 'returns metrics, review, and computed overall_quality (non-zero)' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(:content))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']['complexity']).to eq(1)
      expect(json['review']['score']).to eq(90)
      expect(json['overall_quality']).to eq(80.0)
    end

    it 'returns 0 overall_quality when services report errors' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'failed' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'error' => 'failed' })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['overall_quality']).to eq(0.0)
    end

    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns dashboard summary with computed health_score' do
      fixed_time = Time.new(2024, 1, 1, 12, 0, 0, '+00:00')
      allow(Time).to receive(:now).and_return(fixed_time)

      file_stats = {
        'total_files' => 5,
        'total_lines' => 500,
        'languages' => { 'ruby' => 3, 'python' => 2 }
      }
      review_stats = {
        'average_score' => 90.0,
        'total_issues' => 4,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(:files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(:files))
        .and_return(review_stats)

      post '/dashboard', { files: [{ 'path' => 'a.rb' }, { 'path' => 'b.py' }] }.to_json,
           'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['timestamp']).to eq(fixed_time.iso8601)
      expect(json['file_statistics']).to eq(file_stats)
      expect(json['review_statistics']).to eq(review_stats)
      expect(json['summary']['total_files']).to eq(5)
      expect(json['summary']['total_lines']).to eq(500)
      expect(json['summary']['languages']).to eq(file_stats['languages'])
      expect(json['summary']['average_quality_score']).to eq(90.0)
      expect(json['summary']['total_issues']).to eq(4)
      # health_score = 90 - (4/5*2) - (0.5*30) = 73.4
      expect(json['summary']['health_score']).to eq(73.4)
    end

    it 'returns 0 health_score when services return errors' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'unavailable' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'error' => 'unavailable' })

      post '/dashboard', { files: [{ 'path' => 'a.rb' }] }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['summary']['health_score']).to eq(0.0)
      expect(json['summary']['total_files']).to eq(0)
      expect(json['summary']['total_lines']).to eq(0)
      expect(json['summary']['languages']).to eq({})
      expect(json['summary']['average_quality_score']).to eq(0.0)
      expect(json['summary']['total_issues']).to eq(0)
    end

    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end
  end
end
